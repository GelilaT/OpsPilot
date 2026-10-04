"""Idempotency-Key handling for POST/PATCH (FR-API-03).

A repeat with the same key and body returns the original response; the same key with a different
body returns 409. Keys are scoped per caller (JWT subject) and kept for 24 hours. A first request
reserves the key (state=in_progress) so concurrent duplicates cannot both execute.
"""

import base64
import hashlib
import json
from datetime import datetime, timedelta

import jwt
from sqlalchemy import DateTime, Integer, LargeBinary, String, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.db import Base, get_sessionmaker
from app.core.errors import problem

TTL = timedelta(hours=24)
METHODS = {"POST", "PATCH"}


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"

    subject: Mapped[str] = mapped_column(String(120), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(400))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="in_progress")
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_headers: Mapped[list | None] = mapped_column(JSONB)
    response_body: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _subject(scope: Scope) -> str:
    auth = dict(scope["headers"]).get(b"authorization", b"").decode()
    if auth.lower().startswith("bearer "):
        try:  # signature is verified by the route itself; here we only need a stable caller scope
            return "sub:" + str(jwt.decode(auth[7:], options={"verify_signature": False}).get("sub"))
        except jwt.PyJWTError:
            pass
    return "anon"


class IdempotencyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in METHODS:
            await self.app(scope, receive, send)
            return
        key = dict(scope["headers"]).get(b"idempotency-key", b"").decode().strip()
        if not key:
            await self.app(scope, receive, send)
            return
        if len(key) > 200:
            await problem(400, "invalid_idempotency_key", "Invalid Idempotency-Key",
                          "Idempotency-Key must be at most 200 characters.")(scope, receive, send)
            return

        # Buffer the body so it can be hashed and replayed to the app.
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        req_hash = hashlib.sha256(
            scope["method"].encode() + b" " + scope["path"].encode() + b"\n" + body
        ).hexdigest()
        subject = _subject(scope)

        sm = get_sessionmaker()
        async with sm() as session, session.begin():
            await session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.created_at < func.now() - TTL)
                .where(IdempotencyRecord.subject == subject, IdempotencyRecord.key == key)
            )
            inserted = await session.execute(
                insert(IdempotencyRecord)
                .values(subject=subject, key=key, method=scope["method"], path=scope["path"],
                        request_hash=req_hash, state="in_progress")
                .on_conflict_do_nothing()
                .returning(IdempotencyRecord.key)
            )
            reserved = inserted.scalar_one_or_none() is not None
            existing = None
            if not reserved:
                existing = (await session.execute(
                    select(IdempotencyRecord).where(IdempotencyRecord.subject == subject,
                                                    IdempotencyRecord.key == key)
                )).scalar_one()

        if existing is not None:
            if existing.request_hash != req_hash:
                resp = problem(409, "idempotency_key_reused", "Idempotency key reused",
                               "This Idempotency-Key was already used with a different request.")
            elif existing.state != "done":
                resp = problem(409, "idempotency_in_progress", "Request in progress",
                               "A request with this Idempotency-Key is still being processed; retry shortly.")
            else:
                await send({"type": "http.response.start", "status": existing.status_code,
                            "headers": [(base64.b64decode(k), base64.b64decode(v))
                                        for k, v in existing.response_headers or []]
                            + [(b"idempotent-replayed", b"true")]})
                await send({"type": "http.response.body", "body": existing.response_body or b""})
                return
            await resp(scope, receive, send)
            return

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        status = 500
        headers: list[tuple[bytes, bytes]] = []
        out: list[bytes] = []

        async def capture_send(message: Message) -> None:
            nonlocal status, headers
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                out.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay_receive, capture_send)
        finally:
            async with sm() as session, session.begin():
                rec = await session.get(IdempotencyRecord, (subject, key))
                if rec is not None:
                    if status >= 500:  # server failures are not cached; the client may retry
                        await session.delete(rec)
                    else:
                        keep = [(base64.b64encode(k).decode(), base64.b64encode(v).decode())
                                for k, v in headers if k.lower() not in (b"content-length", b"x-request-id")]
                        rec.state, rec.status_code = "done", status
                        rec.response_headers = json.loads(json.dumps(keep))
                        rec.response_body = b"".join(out)
