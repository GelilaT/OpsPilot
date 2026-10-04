"""MailPort (FR-BRF-05)."""

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class EmailMessage:
    to: tuple[str, ...]
    subject: str
    text: str
    html: str | None = None
    reply_to: str | None = None
    idempotency_key: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DeliveryResult:
    status: Literal["accepted", "sent", "logged"]
    provider: str
    provider_message_id: str | None = None


@runtime_checkable
class MailPort(Protocol):
    provider: str

    async def send(self, message: EmailMessage) -> DeliveryResult: ...
