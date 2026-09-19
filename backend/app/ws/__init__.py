"""SmartQueue Phase 5A realtime package (WS1-Infra).

Owns WebSocket connection management, queue event envelopes and payload
schemas only. No business logic, no models, no migrations, no
notifications/AI.

Single-instance only: connections live in process memory
(see ``manager.ConnectionManager``). Multi-worker / multi-replica fan-out
requires a Redis (or equivalent) pub/sub backing store in the future.
"""
from app.ws.events import QUEUE_EVENTS, build_event
from app.ws.manager import ConnectionManager, manager
from app.ws.schemas import QueueEvent, QueueEventPayload

__all__ = [
    "QUEUE_EVENTS",
    "ConnectionManager",
    "QueueEvent",
    "QueueEventPayload",
    "build_event",
    "manager",
]
