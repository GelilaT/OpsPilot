"""SiteContext: the site, organisation, effective configuration, clock and adapters for one request or
job (SRS glossary; FR-TEN-04). Domain services receive this object instead of reading globals."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.integrations import AdapterRegistry, registry
from app.core.money import Money
from app.core.tenancy.config import EffectiveConfig, resolve_config
from app.core.tenancy.models import Site, SiteClock
from app.core.tenancy.scoping import bind_tenant
from app.ports import IntegrationKind


@dataclass
class SiteContext:
    session: AsyncSession
    site: Site
    config: EffectiveConfig
    actor: str
    registry: AdapterRegistry = field(default=registry)
    _adapters: dict[IntegrationKind, Any] = field(default_factory=dict)

    @property
    def organisation_id(self) -> uuid.UUID:
        return self.site.organisation_id

    @property
    def site_id(self) -> uuid.UUID:
        return self.site.id

    @property
    def currency(self) -> str:
        return self.site.currency

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.site.timezone)

    def money(self, minor: int) -> Money:
        return Money(minor, self.site.currency)

    async def adapter(self, kind: IntegrationKind) -> Any:
        """The configured adapter for this site (site -> organisation -> system default)."""
        if kind not in self._adapters:
            self._adapters[kind] = await self.registry.resolve(self.session, kind, self.organisation_id, self.site_id)
        return self._adapters[kind]

    # ---- clock -------------------------------------------------------------------------------
    async def today(self) -> date:
        """Business date: the simulator clock when simulation is enabled, else today in the site's timezone."""
        if self.config.get("simulation.enabled"):
            clock = (await self.session.execute(
                select(SiteClock).where(SiteClock.site_id == self.site_id))).scalar_one_or_none()
            if clock is not None:
                return clock.business_date
        return datetime.now(self.tz).date()

    async def now(self) -> datetime:
        """Current instant; on the simulator clock this is the business date at the current wall time."""
        real = datetime.now(self.tz)
        today = await self.today()
        if today == real.date():
            return real
        return datetime.combine(today, real.time(), tzinfo=self.tz)

    def local(self, day: date, at: time) -> datetime:
        return datetime.combine(day, at, tzinfo=self.tz)

    def day_bounds_utc(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time(0), tzinfo=self.tz)
        return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


async def build_site_context(session: AsyncSession, organisation_id: uuid.UUID, site_id: uuid.UUID, *,
                             actor: str, reg: AdapterRegistry | None = None) -> SiteContext:
    """Bind the session to the tenant (RLS + repository filters) and resolve configuration."""
    await bind_tenant(session, organisation_id, site_id)
    site = (await session.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
    if site is None:
        raise NotFound("Site not found.")
    config = await resolve_config(session, organisation_id, site_id)
    return SiteContext(session=session, site=site, config=config, actor=actor, registry=reg or registry)
