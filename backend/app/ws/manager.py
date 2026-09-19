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
        phone/email ever forwarded). Routes to
        :meth:`broadcast_to_queue` when ``(barber_id, date)`` are present,
        else to :meth:`broadcast_to_salon`. Unknown event types fall back to
        ``queue.updated``. Returns deliveries; 0 when unroutable.
        """
        try:
            if not isinstance(event, dict):
                return 0
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
            name = etype if etype in QUEUE_EVENTS else "queue.updated"
            payload = sanitize_payload(
                {
                    **data,
                    "barber_id": barber_id,
                    "salon_id": salon_id,
                    "estimated_wait": data.get(
                        "estimated_wait", data.get("estimated_wait_minutes")
                    ),
                    "scope": {
                        "salon_id": salon_id,
                        "barber_id": barber_id,
                        "date": date_str,
                    },
                }
            )
            message = build_event(name, payload)
            try:
                salon_int = int(salon_id) if salon_id is not None else None
            except (TypeError, ValueError):
                salon_int = None
            try:
                barber_int = int(barber_id) if barber_id is not None else None
            except (TypeError, ValueError):
                barber_int = None
            if barber_int is not None and date_str:
                return await self.broadcast_to_queue(
                    barber_int, date_str, message, salon_id=salon_int
                )
            if salon_int is not None:
                return await self.broadcast_to_salon(
                    salon_int, message, date_str
                )
            return 0
        except Exception:
            logger.debug("broadcast_event failed", exc_info=False)
            return 0


# Process-local singleton (single-instance deployment).
manager = ConnectionManager()
