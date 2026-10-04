"""MailPort adapters: SendGrid v3 Mail Send, Resend (fallback) and console (development)."""

import logging
from email.utils import parseaddr

import httpx

from app.ports.errors import InvalidCredentialsError, PermanentError, PortError, RateLimitedError, TransientError
from app.ports.mail import DeliveryResult, EmailMessage

log = logging.getLogger("opspilot.mail")


def _http_error(provider: str, resp: httpx.Response) -> PortError:
    text = resp.text[:300]
    if resp.status_code in (401, 403):
        return InvalidCredentialsError(f"{provider} rejected the API key: {text}", provider=provider)
    if resp.status_code == 429:
        retry = float(resp.headers.get("retry-after", 60) or 60)
        return RateLimitedError(f"{provider} rate limit: {text}", retry_after=retry, provider=provider)
    if resp.status_code >= 500:
        return TransientError(f"{provider} unavailable ({resp.status_code}): {text}", provider=provider)
    return PermanentError(f"{provider} rejected the message ({resp.status_code}): {text}", provider=provider)


class SendGridMail:
    provider = "sendgrid"

    def __init__(self, api_key: str, sender: str, *, base_url: str = "https://api.sendgrid.com",
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise InvalidCredentialsError("SENDGRID_API_KEY is not configured", provider=self.provider)
        self.api_key, self.sender, self.base_url, self.transport = api_key, sender, base_url, transport

    async def send(self, message: EmailMessage) -> DeliveryResult:
        name, address = parseaddr(self.sender)
        content = [{"type": "text/plain", "value": message.text}]
        if message.html:
            content.append({"type": "text/html", "value": message.html})
        body = {
            "personalizations": [{"to": [{"email": t} for t in message.to]}],
            "from": {"email": address, "name": name or None},
            "subject": message.subject,
            "content": content,
            "categories": list(message.tags)[:10] or None,
            "custom_args": {"idempotency_key": message.idempotency_key} if message.idempotency_key else None,
        }
        if message.reply_to:
            body["reply_to"] = {"email": message.reply_to}
        body = {k: v for k, v in body.items() if v is not None}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=15, transport=self.transport) as client:
                resp = await client.post("/v3/mail/send", json=body,
                                         headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as exc:
            raise TransientError(f"SendGrid connection problem: {exc}", provider=self.provider) from exc
        if resp.status_code != 202:
            raise _http_error("SendGrid", resp)
        return DeliveryResult("accepted", self.provider, resp.headers.get("x-message-id"))

    async def check(self) -> str:
        """Validates the key without sending: the key must hold the mail.send scope."""
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=15, transport=self.transport) as client:
                resp = await client.get("/v3/scopes", headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as exc:
            raise TransientError(f"SendGrid connection problem: {exc}", provider=self.provider) from exc
        if resp.status_code != 200:
            raise _http_error("SendGrid", resp)
        if "mail.send" not in resp.json().get("scopes", []):
            raise InvalidCredentialsError("SendGrid key lacks the mail.send scope", provider=self.provider)
        return "API key valid with mail.send scope"


class ResendMail:
    provider = "resend"

    def __init__(self, api_key: str, sender: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise InvalidCredentialsError("RESEND_API_KEY is not configured", provider=self.provider)
        self.api_key, self.sender, self.transport = api_key, sender, transport

    async def send(self, message: EmailMessage) -> DeliveryResult:
        body = {"from": self.sender, "to": list(message.to), "subject": message.subject, "text": message.text}
        if message.html:
            body["html"] = message.html
        if message.reply_to:
            body["reply_to"] = message.reply_to
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if message.idempotency_key:
            headers["Idempotency-Key"] = message.idempotency_key
        try:
            async with httpx.AsyncClient(base_url="https://api.resend.com", timeout=15,
                                         transport=self.transport) as client:
                resp = await client.post("/emails", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise TransientError(f"Resend connection problem: {exc}", provider=self.provider) from exc
        if resp.status_code not in (200, 201):
            raise _http_error("Resend", resp)
        return DeliveryResult("accepted", self.provider, resp.json().get("id"))

    async def check(self) -> str:
        try:
            async with httpx.AsyncClient(base_url="https://api.resend.com", timeout=15,
                                         transport=self.transport) as client:
                resp = await client.get("/domains", headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as exc:
            raise TransientError(f"Resend connection problem: {exc}", provider=self.provider) from exc
        if resp.status_code != 200:
            raise _http_error("Resend", resp)
        return "API key valid"


class ConsoleMail:
    """Development adapter: logs the message and keeps it in an in-memory outbox (also the test fake)."""

    provider = "console"

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> DeliveryResult:
        if not message.to:
            raise PermanentError("Message has no recipients", provider=self.provider)
        self.outbox.append(message)
        log.info("email", extra={"to": list(message.to), "subject": message.subject})
        return DeliveryResult("logged", self.provider, f"console-{len(self.outbox)}")
