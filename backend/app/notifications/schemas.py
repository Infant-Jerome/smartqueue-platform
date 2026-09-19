"""Notification API schemas (N1-Core, Phase 5B). History GET only."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    """Serialized notification history row (no secrets, no full PII)."""

    model_config = ConfigDict(from_attributes=True)

    notification_id: Optional[int] = None
    user_id: Optional[int] = None
    appointment_id: Optional[int] = None
    channel: str
    type: str
    subject: Optional[str] = None
    body: str = ""
    status: str = "pending"
    attempts: int = 0
    created_at: Optional[datetime] = None
