"""Provider contract (N1-Core, Phase 5B)."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Result:
    """Outcome of one provider send attempt. Never raises by itself."""

    success: bool
    error: Optional[str] = None
    provider: str = "base"


class NotificationProvider:
    """Base provider: ``send() -> Result``. Subclass per channel."""

    name = "base"

    def send(
        self,
        *,
        to: str,
        subject: str = "",
        body: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Result:
        raise NotImplementedError
