"""Supplier and line matching against the catalogue (FR-INV-08, FR-INV-09) and price history lookups."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory.models import Ingredient, UnitConversion
from app.domain.purchasing.invoice_rules import (
    is_unit_compatible,
    line_match_score,
    normalise_supplier_name,
    normalise_text,
    normalise_vat_number,
    price_proximity,
    qty_base_for,
)
from app.domain.purchasing.models import LineAlias, PriceObservation, Supplier, SupplierAlias, SupplierProduct


@dataclass(frozen=True)
class SupplierMatch:
    supplier_id: uuid.UUID | None
    method: str | None  # vat | name | alias | trigram
    score: float
    candidates: list[dict]


async def match_supplier(session: AsyncSession, *, name: str | None, vat_number: str | None,
                         threshold: float) -> SupplierMatch:
    """VAT number, then exact normalised name (or alias), then trigram similarity >= threshold."""
    vat = normalise_vat_number(vat_number)
    if vat:
        rows = (await session.execute(select(Supplier.id, Supplier.vat_number).where(Supplier.vat_number.is_not(None)))).all()
        for sid, sv in rows:
            if normalise_vat_number(sv) == vat:
                return SupplierMatch(sid, "vat", 1.0, [])
    norm = normalise_supplier_name(name)
    if not norm:
        return SupplierMatch(None, None, 0.0, [])
    exact = (await session.execute(select(Supplier.id).where(Supplier.normalised_name == norm))).scalar()
    if exact:
        return SupplierMatch(exact, "name", 1.0, [])
    alias = (await session.execute(select(SupplierAlias.supplier_id).where(SupplierAlias.alias == norm))).scalar()
    if alias:
        return SupplierMatch(alias, "alias", 1.0, [])
    rows = (await session.execute(text("""
        SELECT s.id, s.name, GREATEST(similarity(s.normalised_name, :n),
               COALESCE((SELECT max(similarity(a.alias, :n)) FROM supplier_alias a WHERE a.supplier_id = s.id), 0)) AS score
        FROM supplier s WHERE s.active ORDER BY score DESC LIMIT 3
    """), {"n": norm})).all()
    candidates = [{"supplier_id": str(r.id), "name": r.name, "score": round(float(r.score), 3)} for r in rows]
    if rows and float(rows[0].score) >= threshold:
        return SupplierMatch(rows[0].id, "trigram", float(rows[0].score), candidates)
    return SupplierMatch(None, None, float(rows[0].score) if rows else 0.0, candidates)


@dataclass
class ProductInfo:
    id: uuid.UUID
    ingredient_id: uuid.UUID
    sku: str
    name: str
    purchase_unit: str
    pack_size: str | None
    base_qty_per_unit: Decimal
    base_unit: str
    conversions: dict[str, Decimal]
    contract_price_minor: int | None
    contract_valid_until: date | None
    last_price_per_base: Decimal | None


async def supplier_products(session: AsyncSession, site_id: uuid.UUID, supplier_id: uuid.UUID) -> list[ProductInfo]:
    rows = (await session.execute(
        select(SupplierProduct, Ingredient.base_unit).join(Ingredient, Ingredient.id == SupplierProduct.ingredient_id)
        .where(SupplierProduct.supplier_id == supplier_id, SupplierProduct.active.is_(True)))).all()
    if not rows:
        return []
    ingredient_ids = [p.ingredient_id for p, _ in rows]
    conv: dict[uuid.UUID, dict[str, Decimal]] = {}
    for c in (await session.execute(select(UnitConversion).where(
            (UnitConversion.ingredient_id.in_(ingredient_ids)) | (UnitConversion.ingredient_id.is_(None))))).scalars():
        for ing in ([c.ingredient_id] if c.ingredient_id else ingredient_ids):
            conv.setdefault(ing, {})[c.unit] = Decimal(c.factor_to_base)
    last = dict((await session.execute(
        select(PriceObservation.supplier_product_id, PriceObservation.price_per_base_minor)
        .where(PriceObservation.site_id == site_id, PriceObservation.supplier_product_id.in_([p.id for p, _ in rows]))
        .ext(distinct_on(PriceObservation.supplier_product_id))
        .order_by(PriceObservation.supplier_product_id, PriceObservation.observed_on.desc()))).all())
    return [ProductInfo(p.id, p.ingredient_id, p.sku, p.name, p.purchase_unit, p.pack_size, Decimal(p.base_qty_per_unit),
                        base_unit, conv.get(p.ingredient_id, {}), p.contract_price_minor, p.contract_valid_until,
                        Decimal(last[p.id]) if p.id in last else None) for p, base_unit in rows]


@dataclass(frozen=True)
class LineMatch:
    product: ProductInfo | None
    method: str | None  # sku | alias | fuzzy | suggested
    score: float
    candidates: list[dict]


async def match_line(session: AsyncSession, *, supplier_id: uuid.UUID, products: list[ProductInfo],
                     description: str, sku: str | None, uom: str | None, pack_size: str | None,
                     line_total_minor: int | None, quantity: Decimal | None, auto: float, suggest: float) -> LineMatch:
    """SKU mapping, then a confirmed LineAlias, then the fuzzy score (FR-INV-09)."""
    if sku:
        by_sku = next((p for p in products if p.sku.replace(" ", "").upper() == sku.replace(" ", "").upper()), None)
        if by_sku:
            return LineMatch(by_sku, "sku", 1.0, [])
    norm = normalise_text(description)
    alias = (await session.execute(select(LineAlias.supplier_product_id).where(
        LineAlias.supplier_id == supplier_id, LineAlias.normalised_text == norm))).scalar()
    if alias:
        product = next((p for p in products if p.id == alias), None)
        if product:
            return LineMatch(product, "alias", 1.0, [])
    scored = []
    for p in products:
        text_sim = fuzz.token_set_ratio(norm, normalise_text(p.name)) / 100
        compatible = is_unit_compatible(uom, base_unit=p.base_unit, purchase_unit=p.purchase_unit,
                                        base_qty_per_unit=p.base_qty_per_unit, conversions=p.conversions,
                                        pack_size=pack_size)
        price_base = None
        if compatible and quantity and line_total_minor:
            qb = qty_base_for(quantity, uom, pack_size, base_unit=p.base_unit, purchase_unit=p.purchase_unit,
                              base_qty_per_unit=p.base_qty_per_unit, conversions=p.conversions)
            price_base = Decimal(line_total_minor) / qb if qb else None
        score = line_match_score(text_sim, compatible, price_proximity(price_base, p.last_price_per_base))
        scored.append((score, p))
    scored.sort(key=lambda s: s[0], reverse=True)
    candidates = [{"supplier_product_id": str(p.id), "name": p.name, "sku": p.sku, "score": s} for s, p in scored[:3]]
    if scored and scored[0][0] >= auto:
        return LineMatch(scored[0][1], "fuzzy", scored[0][0], candidates)
    if scored and scored[0][0] >= suggest:
        return LineMatch(scored[0][1], "suggested", scored[0][0], candidates)
    return LineMatch(None, None, scored[0][0] if scored else 0.0, candidates)


async def price_history(session: AsyncSession, site_id: uuid.UUID, supplier_product_id: uuid.UUID, before: date,
                        exclude_ref: str) -> list[tuple[date, Decimal]]:
    rows = (await session.execute(
        select(PriceObservation.observed_on, PriceObservation.price_per_base_minor)
        .where(PriceObservation.site_id == site_id, PriceObservation.supplier_product_id == supplier_product_id,
               PriceObservation.observed_on <= before, PriceObservation.source_ref != exclude_ref,
               PriceObservation.source.in_(("invoice", "purchase_order", "seed")))
        .order_by(PriceObservation.observed_on, PriceObservation.id).limit(400))).all()
    return [(d, Decimal(p)) for d, p in rows]

