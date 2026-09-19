"""Pydantic schemas for queue WebSocket messages (Phase 5A, WS1-Infra)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.ws.events import QUEUE_EVENTS


class QueueEventPayload(BaseModel):
    """Safe queue payload. No password/hash/JWT/phone/email by construction."""

    queue_id: Optional[int] = None
    appointment_id: Optional[int] = None
    barber_id: Optional[int] = None
    salon_id: Optional[int] = None
    queue_position: Optional[int] = None
    status: Optional[str] = None
    current_serving: Optional[int] = None
    currently_serving: Optional[int] = None
    estimated_wait: Optional[int] = None
    estimated_wait_minutes: Optional[int] = None
    people_ahead: Optional[int] = None
    updated_at: Optional[str] = None
    scope: Optional[dict[str, Any]] = None
    entries: Optional[list[dict[str, Any]]] = None
    has_queue: Optional[bool] = None
    my_position: Optional[int] = None
    my_status: Optional[str] = None
    my_queue_id: Optional[int] = None

    model_config = {"extra": "ignore"}


class QueueEvent(BaseModel):
    """Wire envelope: ``{"event": <name>, "data": {...}}``."""

    event: str = Field(pattern="^queue\\.[a-z_]+$")
    data: QueueEventPayload = Field(default_factory=QueueEventPayload)

    def model_post_init(self, _context: Any) -> None:
        if self.event not in QUEUE_EVENTS:
            raise ValueError(f"Unknown queue event '{self.event}'")
