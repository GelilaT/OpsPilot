"""Load a SiteWorld from the database so the simulator continues exactly where the ledger is."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy.models import Organisation
from app.domain.inventory.models import SiteIngredient
from app.domain.inventory.services import current_wac, on_hand, receipts_on
from app.domain.purchasing.models import GoodsReceipt, PurchaseOrder, PurchaseOrderLine, SupplierProduct
from app.simulation.catalogue import Catalogue
from app.simulation.profile import OrgProfile, SiteSpec
from app.simulation.profiles import PROFILES
from app.simulation.world import POLineState, POState, SiteWorld, WorldState


@dataclass
class SimTarget:
    profile: OrgProfile
    site: SiteSpec
    catalogue: Catalogue


def resolve_target(org_slug: str, site_code: str) -> SimTarget | None:
    profile = PROFILES.get(org_slug)
    if profile is None:
        return None
    site = next((s for s in profile.sites if s.code == site_code), None)
    if site is None:
        return None
    return SimTarget(profile, site, Catalogue(profile))


async def org_slug(session: AsyncSession, organisation_id: uuid.UUID) -> str | None:
    return (await session.execute(select(Organisation.slug).where(Organisation.id == organisation_id))).scalar()


def day_start(tz: ZoneInfo, day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=tz)


async def stock_view(session: AsyncSession, target: SimTarget, site_id: uuid.UUID, day: date
                     ) -> tuple[dict[str, Decimal], dict[str, Decimal], list[tuple[datetime, str, Decimal]]]:
    """(on hand at start of day, WAC at start of day, receipts booked during the day) by ingredient code."""
    tz = ZoneInfo(target.profile.timezone)
    start = day_start(tz, day)
    by_id = {v: k for k, v in target.catalogue.ingredient_ids.items()}
    stock = {by_id[i]: q for i, q in (await on_hand(session, site_id, at=start)).items() if i in by_id}
    wacs = {by_id[i]: c for i, c in (await current_wac(session, site_id, at=start)).items() if i in by_id}
    receipts = [(at, by_id[i], q) for at, i, q in await receipts_on(session, site_id, start, start + timedelta(days=1))
                if i in by_id]
    return stock, wacs, receipts


async def load_world(session: AsyncSession, target: SimTarget, site_id: uuid.UUID, day: date) -> SiteWorld:
    stock, wacs, receipts = await stock_view(session, target, site_id, day)
    by_id = {v: k for k, v in target.catalogue.ingredient_ids.items()}
    state = WorldState(on_hand=dict(stock), wac=dict(wacs))
    # Receipts already booked today (e.g. an uploaded invoice) are part of today's stock.
    for at, ing, qty in receipts:
        state.on_hand[ing] = state.on_hand.get(ing, Decimal(0)) + qty
        state.receipts_today.append((at, ing, qty))
    rows = (await session.execute(select(SiteIngredient.ingredient_id, SiteIngredient.par_level_base,
                                         SupplierProduct.supplier_id).outerjoin(
        SupplierProduct, SupplierProduct.id == SiteIngredient.default_supplier_product_id).where(
        SiteIngredient.site_id == site_id))).all()
    supplier_codes = {v: k for k, v in target.catalogue.supplier_ids.items()}
    state.par = {by_id[i]: Decimal(p) for i, p, _ in rows if i in by_id and p}
    # A supplier switch executed in the app changes who the kitchen orders from.
    state.suppliers = {by_id[i]: supplier_codes[s] for i, _, s in rows if i in by_id and s in supplier_codes}
    # Open POs, plus any due today whose invoice was posted before the goods were recorded (the van still
    # arrives and the goods receipt is linked to the posted invoice).
    received = select(GoodsReceipt.purchase_order_id).where(GoodsReceipt.purchase_order_id.is_not(None))
    pos = (await session.execute(select(PurchaseOrder).where(
        PurchaseOrder.site_id == site_id, PurchaseOrder.expected_delivery_date >= day,
        PurchaseOrder.status.in_(("sent", "committed")) | (
            PurchaseOrder.status.in_(("part_received", "received")) & (PurchaseOrder.expected_delivery_date == day)
            & PurchaseOrder.id.not_in(received))))).scalars().all()
    for po in pos:
        lines = (await session.execute(select(PurchaseOrderLine).where(
            PurchaseOrderLine.purchase_order_id == po.id))).scalars().all()
        state.open_pos.append(POState(
            id=str(po.id), number=po.number, supplier=supplier_codes.get(po.supplier_id, "?"), order_date=po.order_date,
            delivery_date=po.expected_delivery_date, status=po.status,
            lines=[POLineState(str(line.id), by_id[line.ingredient_id], str(line.supplier_product_id),
                               Decimal(line.qty_units), Decimal(line.qty_base), line.unit_price_minor)
                   for line in lines if line.ingredient_id in by_id],
        ))
    return SiteWorld(target.profile, target.site, target.catalogue, state)
