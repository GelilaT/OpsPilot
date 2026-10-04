"""Integration connections, the adapter registry and external-reference mapping (FR-INT-02, FR-INT-03).

The adapter for each port is chosen per organisation (optionally per site) by an IntegrationConnection
row (kind, provider, secret reference, settings) and resolved at runtime. Changing provider is a
configuration change only. Concrete adapters register themselves at process start-up (composition
root: app.main / app.workers.app), so core and domain code never import them.
"""

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk
from app.core.errors import NotFound, Unprocessable
from app.core.tenancy.scoping import OrgScoped
from app.ports import IntegrationKind
from app.ports.errors import InvalidCredentialsError


class IntegrationConnection(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "integration_connection"
    __table_args__ = (
        CheckConstraint("kind IN ('pos','accounting','ai','mail','weather','calendar','storage')", name="kind_valid"),
        Index("uq_integration_scope_kind", "organisation_id", "site_id", "kind", unique=True,
              postgresql_nulls_not_distinct=True),
    )

    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(40))
    secret_ref: Mapped[str | None] = mapped_column(String(300))  # e.g. env:GEMINI_API_KEY or gcp-sm:projects/..
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(400))


class ExternalRef(UUIDPk, Timestamps, OrgScoped, Base):
    """Vendor identifiers live here, never in domain tables (FR-INT-02)."""

    __tablename__ = "external_ref"
    __table_args__ = (
        Index("uq_external_ref_provider_id", "organisation_id", "provider", "entity_type", "external_id",
              unique=True),
        Index("ix_external_ref_entity", "entity_type", "entity_id"),
    )

    provider: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID]
    external_id: Mapped[str] = mapped_column(String(200))


class SecretResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


class EnvSecretResolver:
    """`env:NAME` references; other schemes are delegated (e.g. gcp-sm: to Secret Manager)."""

    def __init__(self, delegates: dict[str, SecretResolver] | None = None) -> None:
        self.delegates = delegates or {}

    def resolve(self, ref: str) -> str:
        scheme, _, name = ref.partition(":")
        if scheme == "env":
            value = os.environ.get(name)
            if not value:
                raise InvalidCredentialsError(f"Secret {ref} is not set")
            return value
        if scheme in self.delegates:
            return self.delegates[scheme].resolve(name)
        raise InvalidCredentialsError(f"Unsupported secret reference scheme {scheme!r}")


@dataclass(frozen=True)
class AdapterContext:
    """Everything an adapter factory may use. `services` carries process-wide helpers
    (session factory, app settings) supplied by the composition root."""

    kind: IntegrationKind
    provider: str
    organisation_id: uuid.UUID
    site_id: uuid.UUID | None
    settings: dict[str, Any]
    secret: str | None
    services: dict[str, Any] = field(default_factory=dict)


AdapterFactory = Callable[[AdapterContext], Any]


class AdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[tuple[str, str], AdapterFactory] = {}
        self.defaults: dict[str, tuple[str, dict[str, Any], str | None]] = {}
        self.secrets: SecretResolver = EnvSecretResolver()
        self.services: dict[str, Any] = {}

    def register(self, kind: IntegrationKind, provider: str, factory: AdapterFactory) -> None:
        self._factories[(kind.value, provider)] = factory

    def set_default(self, kind: IntegrationKind, provider: str, settings: dict[str, Any] | None = None,
                    secret_ref: str | None = None) -> None:
        """System-default provider used when neither the site nor the organisation configured one."""
        self.defaults[kind.value] = (provider, settings or {}, secret_ref)

    def providers(self, kind: IntegrationKind) -> list[str]:
        return sorted(p for k, p in self._factories if k == kind.value)

    def has(self, kind: IntegrationKind, provider: str) -> bool:
        return (kind.value, provider) in self._factories

    def build(self, kind: IntegrationKind, provider: str, *, organisation_id: uuid.UUID,
              site_id: uuid.UUID | None, settings: dict[str, Any], secret_ref: str | None,
              extra_services: dict[str, Any] | None = None) -> Any:
        factory = self._factories.get((kind.value, provider))
        if factory is None:
            raise Unprocessable(f"No {kind.value} adapter named {provider!r}.", code="unknown_provider")
        secret = self.secrets.resolve(secret_ref) if secret_ref else None
        services = {**self.services, **(extra_services or {})}
        return factory(AdapterContext(kind, provider, organisation_id, site_id, settings, secret, services))

    async def connection_for(self, session: AsyncSession, kind: IntegrationKind, organisation_id: uuid.UUID,
                             site_id: uuid.UUID | None) -> tuple[str, dict[str, Any], str | None, str]:
        """Resolve site -> organisation -> system default. Returns (provider, settings, secret_ref, source)."""
        rows = (await session.execute(select(IntegrationConnection).where(
            IntegrationConnection.organisation_id == organisation_id,
            IntegrationConnection.kind == kind.value,
            IntegrationConnection.enabled.is_(True),
        ))).scalars().all()
        by_site = next((r for r in rows if site_id is not None and r.site_id == site_id), None)
        by_org = next((r for r in rows if r.site_id is None), None)
        chosen = by_site or by_org
        if chosen is not None:
            return chosen.provider, chosen.settings or {}, chosen.secret_ref, "site" if by_site else "organisation"
        if kind.value not in self.defaults:
            raise NotFound(f"No {kind.value} integration is configured.", code="integration_missing")
        provider, settings, secret_ref = self.defaults[kind.value]
        return provider, settings, secret_ref, "system"

    async def resolve(self, session: AsyncSession, kind: IntegrationKind, organisation_id: uuid.UUID,
                      site_id: uuid.UUID | None) -> Any:
        """Adapter for this tenant. The caller's session is offered to adapters that read OpsPilot data
        within the same transaction (the POS simulator)."""
        provider, settings, secret_ref, _ = await self.connection_for(session, kind, organisation_id, site_id)
        return self.build(kind, provider, organisation_id=organisation_id, site_id=site_id,
                          settings=settings, secret_ref=secret_ref, extra_services={"session": session})


registry = AdapterRegistry()
