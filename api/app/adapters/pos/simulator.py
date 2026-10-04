"""PosPort adapter backed by the restaurant simulator (FR-ING-04: simulator and CSV in v1).

It behaves like a POS for a simulated restaurant: guests order against the kitchen's real stock (read
from the ledger in the caller's transaction), so a short delivery shows up as dishes that stop selling.
"""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy.scoping import tenant_unit_of_work
from app.ports.errors import PermanentError
from app.ports.pos import CanonicalCashUp, CanonicalSale, CanonicalShift
from app.simulation.state import SimTarget, resolve_target, stock_view
from app.simulation.world import SiteWorld, WorldState

PROVIDER = "simulator"


class SimulatorPos:
    provider = PROVIDER

    def __init__(self, *, profile: str, site_code: str, organisation_id: uuid.UUID, site_id: uuid.UUID,
                 session: AsyncSession | None = None) -> None:
        target = resolve_target(profile, site_code)
        if target is None:
            raise PermanentError(f"No simulator profile {profile}/{site_code}", provider=PROVIDER)
        self.target: SimTarget = target
        self.organisation_id, self.site_id, self.session = organisation_id, site_id, session
        self._sales: dict[date, list[CanonicalSale]] = {}

    async def _view(self, day: date):
        if self.session is not None:
            return await stock_view(self.session, self.target, self.site_id, day)
        async with tenant_unit_of_work(self.organisation_id, self.site_id) as s:
            return await stock_view(s, self.target, self.site_id, day)

    def _world(self) -> SiteWorld:
        return SiteWorld(self.target.profile, self.target.site, self.target.catalogue, WorldState({}, {}))

    async def fetch_sales(self, day: date) -> list[CanonicalSale]:
        if day not in self._sales:
            opening, _, receipts = await self._view(day)
            sales, _ = self._world().sales(day, opening, receipts)
            self._sales[day] = sales
        return self._sales[day]

    async def fetch_shifts(self, day: date) -> list[CanonicalShift]:
        return self._world().shifts(day)

    async def fetch_cash_ups(self, day: date) -> list[CanonicalCashUp]:
        return [self._world().cash_up(day, await self.fetch_sales(day))]
