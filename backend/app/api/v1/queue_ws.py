"""Queue realtime WebSocket endpoint (SmartQueue Phase 5A, WS1-Infra).

Route: ``WS /api/v1/ws/queue/{salon_id}?token=<JWT>&barber_id=<int>&date=<YYYY-MM-DD>``

Lifecycle: connect -> auth (``decode_access_token`` only, no new auth) ->
authorize (RBAC) -> send initial authorized queue state -> server-push wait
(client messages are ignored safely) -> disconnect cleanup.

Auth failures close with 4401 (missing/invalid/expired/nonexistent user);
authorization failures close with 4403. Reasons are short, non-leaky
strings. No tracebacks are emitted on disconnect/errors.

RBAC / scoping (channel = ``(salon_id, barber_id, date)``):
- customer: own-scope only. Receives own position/status/estimate plus the
  serving summary (``current_serving``); never other customers' rows or PII.
- barber: own ``barber_id`` only (resolved via ``Barber.user_id``). Any other
  requested ``barber_id`` closes with 4403. No ``barber_id`` defaults to own.
- staff / receptionist / admin: full salon scope (any ``barber_id``).

Ping/heartbeat: relies on WebSocket protocol defaults (Starlette/uvicorn
auto-pong); the server loop simply waits for the next message.
"""
from __future__ import annotations

import asyncio
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Appointment, Barber, Queue, Salon, User
from app.ws import events as queue_events
from app.ws.manager import manager

try:
    # WS2 publisher (optional bridge source). Late/soft import: the endpoint
    # works standalone (auth + snapshots) when this module is unavailable.
    from app.services import queue_events as _publisher
except Exception:  # pragma: no cover - publisher not landed yet
    _publisher = None

router = APIRouter()

_STAFF_ROLES = frozenset({"staff", "receptionist", "admin"})
_ACTIVE_STATUSES = ("waiting", "serving")


def _role_of(user: User) -> str:
    role = getattr(user, "role", "")
    value = getattr(role, "value", role)
    return str(value or "").strip().lower()


def _sanitized_entry(row: Queue, current_serving: Optional[int]) -> dict:
    return queue_events.entry_payload(
        queue_id=row.queue_id,
        appointment_id=row.appointment_id,
        barber_id=row.barber_id,
        salon_id=row.salon_id,
        queue_position=row.queue_position,
        status=row.status,
        estimated_wait_minutes=row.estimated_wait_minutes,
        current_serving=current_serving,
        updated_at=row.updated_at,
    )


def _scoped_entries(
    db: Session, salon_id: int, barber_id: Optional[int], target: _date
) -> tuple[list[dict], Optional[int]]:
    """Active (waiting/serving) entries for the channel + serving position."""
    q = (
        db.query(Queue)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Queue.salon_id == salon_id,
            Queue.status.in_(_ACTIVE_STATUSES),
            Appointment.appointment_date == target,
        )
    )
    if barber_id is not None:
        q = q.filter(Queue.barber_id == barber_id)
    rows = q.order_by(Queue.queue_position.asc()).all()
    serving_pos: Optional[int] = None
    for r in rows:
        if r.status == "serving":
            serving_pos = r.queue_position
            break
    return [_sanitized_entry(r, serving_pos) for r in rows], serving_pos


def _customer_snapshot(
    db: Session,
    user: User,
    salon_id: int,
    barber_id: Optional[int],
    target: _date,
) -> dict:
    """Own position + serving summary only; no other customers, no PII."""
    q = (
        db.query(Queue, Appointment)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Appointment.customer_id == user.user_id,
            Queue.salon_id == salon_id,
            Appointment.appointment_date == target,
        )
        .order_by(Appointment.created_at.desc())
    )
    if barber_id is not None:
        q = q.filter(Queue.barber_id == barber_id)
    mine = q.first()
    _, serving_pos = _scoped_entries(db, salon_id, barber_id, target)
    scope = {
        "salon_id": salon_id,
        "barber_id": barber_id,
        "date": target.isoformat(),
    }
    if mine is None:
        return queue_events.sanitize_payload(
            {
                "has_queue": False,
                "current_serving": serving_pos,
                "currently_serving": serving_pos,
                "scope": scope,
            }
        )
    entry, _ = mine
    ahead = (
        db.query(Queue)
        .join(Appointment, Queue.appointment_id == Appointment.appointment_id)
        .filter(
            Queue.status == "waiting",
            Queue.queue_position < entry.queue_position,
            Appointment.appointment_date == target,
            Queue.barber_id == entry.barber_id,
        )
        .count()
    )
    return queue_events.sanitize_payload(
        {
            "has_queue": True,
            "my_queue_id": entry.queue_id,
            "queue_id": entry.queue_id,
            "my_position": entry.queue_position,
            "queue_position": entry.queue_position,
            "my_status": entry.status,
            "status": entry.status,
            "people_ahead": ahead,
            "estimated_wait": entry.estimated_wait_minutes,
            "estimated_wait_minutes": entry.estimated_wait_minutes,
            "current_serving": serving_pos,
            "currently_serving": serving_pos,
            "barber_id": entry.barber_id,
            "salon_id": entry.salon_id,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
            "scope": scope,
        }
    )


@router.websocket("/ws/queue/{salon_id}")
async def queue_websocket(
    websocket: WebSocket,
    salon_id: int,
    token: Optional[str] = Query(default=None),
    barber_id: Optional[int] = Query(default=None),
    date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    # ---- parse date (default today) before accepting ---------------------
    try:
        target: _date = _date.fromisoformat(date) if date else _date.today()
    except (ValueError, TypeError):
        await websocket.close(code=4400, reason="Invalid date, use YYYY-MM-DD")
        return

    # ---- auth: reuse decode_access_token only ----------------------------
    if not token:
        await websocket.close(code=4401, reason="Missing token")
        return
    try:
        from app.core.security import decode_access_token

        payload = decode_access_token(token)
    except Exception:
        payload = None
    if not payload:
        await websocket.close(code=4401, reason="Invalid or expired token")
        return
    sub = payload.get("sub")
    try:
        uid = int(sub) if sub is not None else None
    except (TypeError, ValueError):
        uid = None
    user: Optional[User] = None
    if uid is not None:
        try:
            user = db.query(User).filter(User.user_id == uid).first()
        except Exception:
            user = None
    if user is None:
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    role = _role_of(user)
    effective_barber = barber_id

    # ---- salon scope must exist (unknown salon -> 4404) ----------------------
    try:
        salon_exists = (
            db.query(Salon).filter(Salon.salon_id == salon_id).first() is not None
        )
    except Exception:
        salon_exists = True  # never fail auth on a lookup error; fail open here
    if not salon_exists:
        await websocket.close(code=4404, reason="Salon not found")
        return

    # ---- authorize (RBAC) --------------------------------------------------
    try:
        if role == "barber":
            profile = (
                db.query(Barber).filter(Barber.user_id == user.user_id).first()
            )
            if profile is None:
                await websocket.close(code=4403, reason="Barber profile not found")
                return
            if barber_id is not None and barber_id != profile.barber_id:
                await websocket.close(code=4403, reason="Access denied")
                return
            effective_barber = profile.barber_id
        elif role == "customer":
            pass  # own-scope enforced in the snapshot, not by closing.
        elif role in _STAFF_ROLES:
            pass  # full salon scope.
        else:
            await websocket.close(code=4403, reason="Insufficient permissions")
            return
    except (ConnectionError, RuntimeError):
        return

    date_str = target.isoformat()

    # ---- register ----------------------------------------------------------
    try:
        await manager.connect(
            websocket,
            salon_id=salon_id,
            barber_id=effective_barber,
            date_str=date_str,
            user_id=user.user_id,
            role=role,
        )
    except Exception:
        return

    # ---- initial authorized state ------------------------------------------
    try:
        if role == "customer":
            data = _customer_snapshot(db, user, salon_id, effective_barber, target)
        else:
            entries, serving_pos = _scoped_entries(
                db, salon_id, effective_barber, target
            )
            data = queue_events.sanitize_payload(
                {
                    "entries": entries,
                    "current_serving": serving_pos,
                    "currently_serving": serving_pos,
                    "scope": {
                        "salon_id": salon_id,
                        "barber_id": effective_barber,
                        "date": date_str,
                    },
                }
            )
        ok = await manager.send_personal(
            websocket, queue_events.build_event("queue.updated", data)
        )
        if not ok:
            return
    except Exception:
        manager.disconnect(websocket)
        return

    # ---- server-push wait; client messages ignored safely -------------------
    # Bridge: forward post-commit publisher events (WS2 outbox/subscribers)
    # onto this socket's channel. The subscriber runs in whatever thread the
    # REST mutation committed on, so delivery is scheduled thread-safely onto
    # this connection's event loop. Unsubscribed on disconnect (no leaks).
    _bridge_on = False
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None
    if _publisher is not None and _loop is not None:
        def _forward(published: dict) -> None:
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    manager.broadcast_event(published), _loop
                )

                def _swallow(fut) -> None:
                    try:
                        if not fut.cancelled():
                            fut.exception()
                    except Exception:
                        pass

                try:
                    fut.add_done_callback(_swallow)
                except Exception:
                    pass
            except RuntimeError:
                # Loop closed: drop this subscriber so stale references
                # never accumulate.
                try:
                    _publisher.unsubscribe(_forward)
                except Exception:
                    pass
            except Exception:
                pass

        try:
            _publisher.subscribe(_forward)
            _bridge_on = True
        except Exception:
            _bridge_on = False

    try:
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except (RuntimeError, ValueError):
                break
            except Exception:
                break
            # Intentionally no echo/broadcast of untrusted client content.
    finally:
        if _bridge_on:
            try:
                _publisher.unsubscribe(_forward)
            except Exception:
                pass
        manager.disconnect(websocket)
