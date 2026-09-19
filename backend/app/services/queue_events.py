"""WS2 queue-event publisher (SmartQueue Phase 5A).

Ownership: WS2-Events owns this file only (+ minimal hook lines in the
service/route files listed below). WS manager / endpoint files are owned by
another workstream -- this module NEVER imports them at module load time.

Contract:
- Queue Service remains the SOLE wait-estimate source. This publisher performs
  NO independent calculation: it only forwards ``entry.estimated_wait_minutes``
  / ``entry.queue_position`` values already committed by ``queue_service``.
- NEVER broadcast before commit. All ``publish_*`` helpers must be called
  AFTER ``db.commit()`` succeeds (service or route post-commit). Failed
  transactions return/raise before the emit line, so no broadcast happens.
- ``publish()`` is sync-callable and async-safe: it appends to an in-memory
  outbox, notifies in-process subscribers, and -- only when an event loop is
  already running -- schedules the async manager broadcast as a task. It never
  blocks REST, never creates/closes loops, and never raises (log only).

Manager interop (late binding):
- ``_abroadcast()`` late-imports the WS manager owned by WS1 (tries known
  candidate paths) and awaits whichever send method exists
  (``broadcast`` / ``send_to_scope`` / ``send`` / ``publish``). If no manager
  is importable yet, the event stays in the outbox for the manager to drain.
"""

import asyncio
import logging
from datetime import date as _date
from datetime import datetime as _datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

EVENT_CREATED = "queue.created"
EVENT_SERVING = "queue.serving"
EVENT_COMPLETED = "queue.completed"
EVENT_SKIPPED = "queue.skipped"
EVENT_CANCELLED = "queue.cancelled"
EVENT_UPDATED = "queue.updated"

# Queue-status -> event-type map (queue_service normalizes in_progress->serving
# before calling us, so we only see stored values here).
_STATUS_TO_EVENT = {
    "waiting": EVENT_UPDATED,
    "serving": EVENT_SERVING,
    "completed": EVENT_COMPLETED,
    "no_show": EVENT_SKIPPED,
    "cancelled": EVENT_CANCELLED,
}

# Candidate WS-manager import paths (owned by WS1; may not exist yet).
_MANAGER_CANDIDATES = (
    "app.api.v1.websocket",
    "app.api.v1.ws",
    "app.websockets.manager",
    "app.core.ws_manager",
    "app.core.websocket",
)

_OUTBOX: list[dict] = []
_SUBSCRIBERS: list[Callable[[dict], Any]] = []


# ---------------------------------------------------------------------------
# Builders (pure: attribute reads only, no DB access, no wait calc)
# ---------------------------------------------------------------------------

def _iso(value: Any) -> Any:
    if isinstance(value, (_date, _datetime)):
        return value.isoformat()
    return value


def _g(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def build_event(
    event_type: str,
    *,
    salon_id: Any = None,
    barber_id: Any = None,
    date: Any = None,
    queue_id: Any = None,
    appointment_id: Any = None,
    status: Any = None,
    queue_position: Any = None,
    estimated_wait_minutes: Any = None,
    confidence: Any = None,
) -> dict:
    """Build a scoped queue event envelope (pure data, no I/O)."""
    return {
        "type": event_type,
        "version": 1,
        "scope": {
            "salon_id": salon_id,
            "barber_id": barber_id,
            "date": _iso(date),
        },
        "data": {
            "queue_id": queue_id,
            "appointment_id": appointment_id,
            "status": status,
            "queue_position": queue_position,
            # Forwarded verbatim from Queue Service; never computed here.
            "estimated_wait_minutes": estimated_wait_minutes,
            # Phase 5C (S2-Integrate): SAWTE confidence, forwarded verbatim
            # from the service layer (or None when unavailable). No calc here.
            "confidence": confidence,
        },
    }


def event_from_rows(
    event_type: str, entry: Any = None, appointment: Any = None, **overrides: Any
) -> dict:
    """Build an event from committed ORM rows (attribute reads only).

    ``appointment`` supplies scope fallback (date) when the entry lacks it.
    Explicit ``overrides`` win (used by routes after reschedules).
    """
    appt_date = _g(appointment, "appointment_date", None)
    data = {
        "salon_id": _g(entry, "salon_id", _g(appointment, "salon_id", None)),
        "barber_id": _g(entry, "barber_id", _g(appointment, "barber_id", None)),
        "date": appt_date,
        "queue_id": _g(entry, "queue_id", None),
        "appointment_id": _g(
            entry, "appointment_id", _g(appointment, "appointment_id", None)
        ),
        "status": _g(entry, "status", _g(appointment, "status", None)),
        "queue_position": _g(entry, "queue_position", None),
        "estimated_wait_minutes": _g(entry, "estimated_wait_minutes", None),
        # Phase 5C (S2-Integrate): forward SAWTE confidence when present on
        # the entry (transient attr set post-commit by queue_service) or via
        # explicit override -- verbatim, never computed here.
        "confidence": _g(entry, "confidence", None),
    }
    data.update({k: v for k, v in overrides.items() if v is not None})
    return build_event(event_type, **data)


# ---------------------------------------------------------------------------
# Transport: outbox + subscribers + async manager broadcast (best effort)
# ---------------------------------------------------------------------------

def subscribe(fn: Callable[[dict], Any]) -> Callable[[dict], Any]:
    """Register an in-process subscriber (WS manager or tests)."""
    _SUBSCRIBERS.append(fn)
    return fn


def unsubscribe(fn: Callable[[dict], Any]) -> None:
    try:
        _SUBSCRIBERS.remove(fn)
    except ValueError:
        pass


def peek_outbox() -> list[dict]:
    return list(_OUTBOX)


def drain_outbox() -> list[dict]:
    events = list(_OUTBOX)
    _OUTBOX.clear()
    return events


def clear_outbox() -> None:
    _OUTBOX.clear()


async def _abroadcast(event: dict) -> None:
    """Await the WS manager broadcast (late-bound; no-op if unavailable)."""
    for path in _MANAGER_CANDIDATES:
        try:
            import importlib

            module = importlib.import_module(path)
        except Exception:
            continue
        manager = getattr(module, "manager", None) or getattr(
            module, "ws_manager", None
        )
        if manager is None:
            continue
        for method_name in ("broadcast", "send_to_scope", "publish", "send"):
            meth = getattr(manager, method_name, None)
            if callable(meth):
                try:
                    result = meth(event)
                    if asyncio.iscoroutine(result):
                        await result
                    return
                except Exception:
                    logger.exception("queue_events: manager.%s failed", method_name)
                    return
    # No manager yet (WS1 pending) -- outbox retains the event. Debug only.
    logger.debug("queue_events: no WS manager available; outbox=%d", len(_OUTBOX))


def _schedule_async_broadcast(event: dict) -> None:
    """Schedule ``_abroadcast`` only if a loop is already running.

    Sync REST (incl. TestClient) has no running loop: skip scheduling and
    leave the event in the outbox for the manager to drain. Never calls
    ``asyncio.run`` / ``run_until_complete`` (would block or raise).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no running loop -- store-only (manager drains later)
    try:
        loop.create_task(_abroadcast(event))
    except Exception:
        logger.exception("queue_events: failed to schedule broadcast")


def publish(event: dict) -> None:
    """Sync-callable entry point: outbox + subscribers + async broadcast.

    NEVER raises: publish errors are logged only so REST is never broken.
    MUST be called AFTER ``db.commit()`` succeeds (never before).
    """
    try:
        if not isinstance(event, dict):
            logger.warning("queue_events: ignoring non-dict event %r", event)
            return
        _OUTBOX.append(event)
        for cb in list(_SUBSCRIBERS):
            try:
                result = cb(event)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        logger.debug("queue_events: async subscriber skipped (no loop)")
                        continue
                    loop.create_task(result)
            except Exception:
                logger.exception("queue_events: subscriber failed")
        _schedule_async_broadcast(event)
    except Exception:
        logger.exception("queue_events: publish failed (ignored)")


# ---------------------------------------------------------------------------
# Typed helpers (scope-aware; forward committed values only)
# ---------------------------------------------------------------------------

def _publish_typed(
    event_type: str, entry: Any = None, appointment: Any = None, **overrides: Any
) -> None:
    try:
        publish(event_from_rows(event_type, entry, appointment, **overrides))
    except Exception:
        logger.exception("queue_events: %s build/publish failed (ignored)", event_type)


def publish_creation(entry: Any = None, appointment: Any = None, **overrides: Any) -> None:
    """Booking / join: a new waiting row was committed."""
    _publish_typed(EVENT_CREATED, entry, appointment, **overrides)


def publish_serve(entry: Any = None, appointment: Any = None, **overrides: Any) -> None:
    """waiting -> serving (incl. serve-next)."""
    _publish_typed(EVENT_SERVING, entry, appointment, **overrides)


def publish_complete(entry: Any = None, appointment: Any = None, **overrides: Any) -> None:
    """serving -> completed."""
    _publish_typed(EVENT_COMPLETED, entry, appointment, **overrides)


def publish_skip(entry: Any = None, appointment: Any = None, **overrides: Any) -> None:
    """waiting -> no_show (skip)."""
    _publish_typed(EVENT_SKIPPED, entry, appointment, **overrides)


def publish_cancel(entry: Any = None, appointment: Any = None, **overrides: Any) -> None:
    """waiting/serving -> cancelled."""
    _publish_typed(EVENT_CANCELLED, entry, appointment, **overrides)


def publish_updated(entry: Any = None, appointment: Any = None, **overrides: Any) -> None:
    """Generic update / wait-recompute / position-change notification."""
    _publish_typed(EVENT_UPDATED, entry, appointment, **overrides)


def publish_for_queue_status(
    queue_status: Any, entry: Any = None, appointment: Any = None, **overrides: Any
) -> None:
    """Map a stored queue status to its event (fallback: updated)."""
    key = str(queue_status or "").strip().lower()
    if key == "in_progress":
        key = "serving"
    _publish_typed(_STATUS_TO_EVENT.get(key, EVENT_UPDATED), entry, appointment, **overrides)
