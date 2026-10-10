"""In-memory WebSocket connection manager (SmartQueue Phase 5A, WS1-Infra).

Single-instance only: all sockets are held in a process-local dict keyed by
the ``WebSocket`` object with its subscribed channel
``(salon_id, barber_id, date_str)`` plus the authenticated
``(user_id, role)``. There is no cross-process fan-out; running multiple
workers/replicas will each serve only their own connections. Future work:
back ``broadcast_*`` with Redis pub/sub (publish event + channel, subscribe
per instance, then fan out to local sockets) without changing call sites.

Robustness contract: ``send_*`` / ``broadcast_*`` never raise on a dead or
broken socket. Failed sockets are cleaned up (removed from the registry)
and the remaining sends continue, so one bad client can never crash a
broadcast or the server process.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import WebSocket

from app.ws.events import QUEUE_EVENTS, build_event, sanitize_payload

logger = logging.getLogger(__name__)

# Roles that receive the full channel payload on pushes. Every other role
# (notably ``customer``) receives a per-recipient scoped variant that never
# contains another customer's appointment_id/queue_id. Unknown roles fall
# closed to the customer-scoped variant.
_FULL_PAYLOAD_ROLES = frozenset({"staff", "receptionist", "admin", "barber"})


def _parse_queue_event(event: Any) -> Optional[dict[str, Any]]:
    """Parse a publisher envelope into routable parts; None if unroutable.

    Returns ``{"name", "salon_id", "barber_id", "date_str", "salon_int",
    "barber_int", "data"}``. ``customer_id`` stays inside ``data`` (raw,
    pre-sanitize) for per-recipient scoping; it is never wired to clients.
    """
    if not isinstance(event, dict):
        return None
    etype = str(event.get("type") or event.get("event") or "")
    scope = event.get("scope") or {}
    data = event.get("data") or {}
    if not isinstance(scope, dict):
        scope = {}
    if not isinstance(data, dict):
        data = {}
    salon_id = scope.get("salon_id", data.get("salon_id"))
    barber_id = scope.get("barber_id", data.get("barber_id"))
    date_val = scope.get("date", data.get("date"))
    if hasattr(date_val, "isoformat"):
        try:
            date_str: Optional[str] = date_val.isoformat()
        except Exception:
            date_str = None
    elif date_val:
        date_str = str(date_val)
    else:
        date_str = None
    try:
        salon_int = int(salon_id) if salon_id is not None else None
    except (TypeError, ValueError):
        salon_int = None
    try:
        barber_int = int(barber_id) if barber_id is not None else None
    except (TypeError, ValueError):
        barber_int = None
    if (barber_int is None or not date_str) and salon_int is None:
        return None
    name = etype if etype in QUEUE_EVENTS else "queue.updated"
    return {
        "name": name,
        "salon_id": salon_id,
        "barber_id": barber_id,
        "date_str": date_str,
        "salon_int": salon_int,
        "barber_int": barber_int,
        "data": data,
    }


def _full_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    """Unscoped channel payload for staff roles (identical to pre-fix wire)."""
    data = parsed["data"]
    return sanitize_payload(
        {
            **data,
            "barber_id": parsed["barber_id"],
            "salon_id": parsed["salon_id"],
            "estimated_wait": data.get(
                "estimated_wait", data.get("estimated_wait_minutes")
            ),
            "scope": {
                "salon_id": parsed["salon_id"],
                "barber_id": parsed["barber_id"],
                "date": parsed["date_str"],
            },
        }
    )


def _customer_payload(
    parsed: dict[str, Any], user_id: Any
) -> dict[str, Any]:
    """Per-recipient payload for a customer socket.

    Own entry (event owner == this user): own queue/appointment ids plus
    position/status/waits and the serving summary. Anything else
    (foreign entry, or owner unknown -> fail closed): serving summary only
    (``current_serving``/``currently_serving`` + ``scope``) with no
    appointment_id/queue_id/position/status keys at all.
    """
    data = parsed["data"]
    scope = {
        "salon_id": parsed["salon_id"],
        "barber_id": parsed["barber_id"],
        "date": parsed["date_str"],
    }
    status = str(data.get("status") or "").strip().lower()
    serving_pos = data.get("queue_position") if status == "serving" else None
    try:
        owner = int(data.get("customer_id")) if data.get("customer_id") is not None else None
    except (TypeError, ValueError):
        owner = None
    if owner is not None and owner == user_id:
        return sanitize_payload(
            {
                "queue_id": data.get("queue_id"),
                "appointment_id": data.get("appointment_id"),
                "queue_position": data.get("queue_position"),
                "status": data.get("status"),
                "estimated_wait": data.get(
                    "estimated_wait", data.get("estimated_wait_minutes")
                ),
                "estimated_wait_minutes": data.get("estimated_wait_minutes"),
                "confidence": data.get("confidence"),
                "barber_id": parsed["barber_id"],
                "salon_id": parsed["salon_id"],
                "current_serving": serving_pos,
                "currently_serving": serving_pos,
                "scope": scope,
            }
        )
    return sanitize_payload(
        {
            "current_serving": serving_pos,
            "currently_serving": serving_pos,
            "scope": scope,
        }
    )


class ConnectionManager:
    """Track active queue WebSocket connections scoped by channel."""

    def __init__(self) -> None:
        # WebSocket -> {"salon_id": int, "barber_id": int | None,
        #               "date": str, "user_id": int, "role": str}
        self._connections: dict[WebSocket, dict[str, Any]] = {}

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(
        self,
        websocket: WebSocket,
        *,
        salon_id: int,
        barber_id: Optional[int],
        date_str: str,
        user_id: int,
        role: str,
    ) -> None:
        """Accept the socket and register its channel subscription."""
        await websocket.accept()
        self._connections[websocket] = {
            "salon_id": salon_id,
            "barber_id": barber_id,
            "date": date_str,
            "user_id": user_id,
            "role": role,
        }

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a socket; safe to call for unknown/already-removed sockets."""
        self._connections.pop(websocket, None)

    def _matches_queue(
        self,
        info: dict[str, Any],
        barber_id: Optional[int],
        date_str: Optional[str],
        salon_id: Optional[int] = None,
    ) -> bool:
        if salon_id is not None and info.get("salon_id") != salon_id:
            return False
        if date_str is not None and info.get("date") != date_str:
            return False
        if barber_id is not None:
            # A subscription with barber_id=None is salon-wide (staff/admin)
            # and receives every barber channel in that salon+date.
            sub = info.get("barber_id")
            if sub is not None and sub != barber_id:
                return False
        return True

    def scoped_message_for(
        self, event: dict, info: dict[str, Any]
    ) -> Optional[dict]:
        """Build the push message for ONE socket; None if off-channel.

        Staff roles (staff/receptionist/admin/own-barber) get the full
        channel payload; customer (and unknown) roles get a per-recipient
        scoped variant (own entry or serving-summary-only). Pure w.r.t.
        the registry (no sends); never raises.
        """
        try:
            parsed = _parse_queue_event(event)
            if parsed is None:
                return None
            if not self._matches_event(info, parsed):
                return None
            role = str(info.get("role") or "").strip().lower()
            if role in _FULL_PAYLOAD_ROLES:
                return build_event(parsed["name"], _full_payload(parsed))
            # Customer pushes are always queue.updated (snapshot-shaped).
            return build_event(
                "queue.updated", _customer_payload(parsed, info.get("user_id"))
            )
        except Exception:
            logger.debug("scoped_message_for failed", exc_info=False)
            return None

    def _matches_event(self, info: dict[str, Any], parsed: dict[str, Any]) -> bool:
        barber_int = parsed["barber_int"]
        date_str = parsed["date_str"]
        salon_int = parsed["salon_int"]
        if barber_int is not None and date_str:
            return self._matches_queue(info, barber_int, date_str, salon_int)
        if salon_int is not None:
            return info.get("salon_id") == salon_int and (
                date_str is None or info.get("date") == date_str
            )
        return False

    async def deliver_event_to(self, websocket: WebSocket, event: dict) -> bool:
        """Deliver one published event to ONE socket (scoped). Never raises.

        Channel mismatches and unroutable events are a silent no-op (True:
        nothing to deliver, socket stays). Returns False (and cleans up)
        only when the socket itself is dead.
        """
        try:
            info = self._connections.get(websocket)
            if info is None:
                return False
            message = self.scoped_message_for(event, info)
            if message is None:
                return True
            return await self.send_personal(websocket, message)
        except Exception:
            logger.debug("deliver_event_to failed", exc_info=False)
            return False

    async def send_personal(self, websocket: WebSocket, message: dict) -> bool:
        """Send to one socket. Returns False (and cleans up) on failure."""
        try:
            await websocket.send_json(message)
            return True
        except Exception:
            logger.debug("Dropping dead websocket (send_personal)", exc_info=False)
            self.disconnect(websocket)
            try:
                await websocket.close()
            except Exception:
                pass
            return False

    async def _broadcast_to(
        self, targets: list[WebSocket], message: dict
    ) -> int:
        """Best-effort send to targets; dead sockets are cleaned up.

        Returns the number of successful deliveries. Never raises.
        """
        delivered = 0
        dead: list[WebSocket] = []
        for ws in targets:
            if ws not in self._connections:
                continue
            try:
                await ws.send_json(message)
                delivered += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
            try:
                await ws.close()
            except Exception:
                pass
        return delivered

    async def broadcast_to_queue(
        self,
        barber_id: int,
        date_str: str,
        message: dict,
        salon_id: Optional[int] = None,
    ) -> int:
        """Push to every connection on the ``(salon_id?, barber_id, date)`` channel.

        ``salon_id`` is optional for backwards/forwards compatibility of the
        documented ``broadcast_to_queue(barber_id, date)`` signature; when
        given, only that salon's subscribers receive the event.
        """
        targets = [
            ws
            for ws, info in list(self._connections.items())
            if self._matches_queue(info, barber_id, date_str, salon_id)
        ]
        try:
            return await self._broadcast_to(targets, message)
        except Exception:
            logger.debug("broadcast_to_queue failed", exc_info=False)
            return 0

    async def broadcast_to_salon(
        self,
        salon_id: int,
        message: dict,
        date_str: Optional[str] = None,
    ) -> int:
        """Push to every connection subscribed to ``salon_id`` (opt. date)."""
        targets = [
            ws
            for ws, info in list(self._connections.items())
            if info.get("salon_id") == salon_id
            and (date_str is None or info.get("date") == date_str)
        ]
        try:
            return await self._broadcast_to(targets, message)
        except Exception:
            logger.debug("broadcast_to_salon failed", exc_info=False)
            return 0

    async def broadcast_event(self, event: dict) -> int:
        """Deliver a publisher envelope to the matching channel. Never raises.

        Accepts the ``app.services.queue_events`` envelope
        ``{"type", "version", "scope": {salon_id, barber_id, date},
        "data": {queue_id, appointment_id, status, queue_position,
        estimated_wait_minutes}}`` and re-emits it as this package's
        ``{"event", "data"}`` envelope (sanitized: no password/hash/JWT/
        phone/email ever forwarded).

        Per-recipient scoping: each socket on the channel gets exactly one
        copy, but staff roles receive the full channel payload while
        customer sockets receive only their own entry (or a
        serving-summary-only payload for other customers' events). Routes
        to queue-channel subscribers when ``(barber_id, date)`` are
        present, else to salon subscribers. Unknown event types fall back
        to ``queue.updated``. Returns deliveries; 0 when unroutable.
        """
        try:
            parsed = _parse_queue_event(event)
            if parsed is None:
                return 0
            delivered = 0
            dead: list[WebSocket] = []
            for ws, info in list(self._connections.items()):
                if ws not in self._connections:
                    continue
                try:
                    role = str(info.get("role") or "").strip().lower()
                    if role in _FULL_PAYLOAD_ROLES:
                        message: Optional[dict] = None
                        if self._matches_event(info, parsed):
                            message = build_event(
                                parsed["name"], _full_payload(parsed)
                            )
                    else:
                        message = self.scoped_message_for(event, info)
                    if message is None:
                        continue
                    await ws.send_json(message)
                    delivered += 1
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(ws)
                try:
                    await ws.close()
                except Exception:
                    pass
            return delivered
        except Exception:
            logger.debug("broadcast_event failed", exc_info=False)
            return 0


# Process-local singleton (single-instance deployment).
manager = ConnectionManager()
