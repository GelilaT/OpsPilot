"""Seed generator (FR-ING-01, SRS Appendix C).

Parameterised by organisation profile; the same code seeds any number of organisations and sites. Runs
the restaurant simulator day by day in memory and bulk-loads the result with COPY. Deterministic: the
same profiles and dates always yield the same data.
"""

import copy
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql

from app.core.tenancy.config import REGISTRY
from app.domain.sales.services import cash_up_row, dayparts_from_config, sale_rows, shift_row
from app.seed.users import DEMO_PASSWORD, better_auth_hash
from app.simulation.catalogue import Catalogue, holidays, sid, weather
from app.simulation.persist import count_rows, delivery_rows, movement_row, po_rows, po_status_after, waste_row
from app.simulation.profile import OrgProfile, SiteSpec
from app.simulation.scenarios import SEED_DAYS, SEED_END
from app.simulation.world import SiteWorld, WorldState

log = logging.getLogger("opspilot.seed")

JSONB_COLUMNS = {"reason_codes", "delivery_weekdays", "settings", "value", "before", "after",
                 "match_candidates"}


@dataclass
class Rows:
    tables: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))

    def add(self, table: str, rows: dict | list[dict]) -> None:
        self.tables[table].extend(rows if isinstance(rows, list) else [rows])


# Insert order respects foreign keys.
TABLE_ORDER = [
    "organisation", "site", "user", "account", "organisation_user", "membership", "config_value",
    "integration_connection", "site_clock", "ingredient", "unit_conversion", "supplier", "supplier_alias",
    "supplier_product", "site_ingredient", "menu_item", "menu_item_price", "recipe", "recipe_line", "external_ref",
    "weather_day", "purchase_order", "purchase_order_line", "goods_receipt", "goods_receipt_line",
    "invoice", "invoice_line", "price_observation", "sales_order", "sales_order_line", "shift", "cash_up",
    "stock_movement", "waste_entry",
    "stock_count", "stock_count_line", "audit_event",
]


def _cell(column: str, value: Any) -> Any:
    if column in JSONB_COLUMNS and value is not None:
        return json.dumps(value, default=str)
    return value


async def copy_rows(conn: psycopg.AsyncConnection, rows: Rows) -> dict[str, int]:
    counts = {}
    for table in TABLE_ORDER:
        data = rows.tables.get(table)
        if not data:
            continue
        cols = list(data[0])
        statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier(table), sql.SQL(", ").join(sql.Identifier(c) for c in cols))
        async with conn.cursor() as cur, cur.copy(statement) as cp:
            for row in data:
                await cp.write_row([_cell(c, row.get(c)) for c in cols])
        counts[table] = len(data)
    return counts


def _now() -> datetime:
    return datetime.now(UTC)


def reference_rows(org: OrgProfile, cat: Catalogue, rows: Rows, start: date) -> None:
    """Organisation, sites, users, configuration, integrations, catalogue, menu and recipes."""
    org_id = cat.org_id
    now = _now()
    ts = {"created_at": now, "updated_at": now}
    rows.add("organisation", {"id": org_id, "name": org.name, "slug": org.slug, "default_currency": org.currency,
                              "default_timezone": org.timezone, **ts})
    for site in org.sites:
        rows.add("site", {"id": cat.site_id(site), "organisation_id": org_id, "name": site.name,
                          "timezone": org.timezone, "currency": org.currency, "vat_scheme": "uk_standard",
                          "region": org.region, "address": site.address, "latitude": site.latitude,
                          "longitude": site.longitude, "covers": site.covers, **ts})
        rows.add("site_clock", {"id": sid(org.slug, "clock", site.code), "organisation_id": org_id,
                                "site_id": cat.site_id(site), "business_date": SEED_END, "updated_at": now})
        rows.add("integration_connection", {
            "id": sid(org.slug, "integration", "pos", site.code), "organisation_id": org_id,
            "site_id": cat.site_id(site), "kind": "pos", "provider": "simulator", "secret_ref": None,
            "settings": {"profile": org.slug, "site_code": site.code}, "enabled": True, "last_tested_at": None,
            "last_test_status": None, **ts})
    site_ids = {s.code: cat.site_id(s) for s in org.sites}

    for user in org.users:
        user_id = sid(org.slug, "user", user.email).hex
        rows.add("user", {"id": user_id, "name": user.name, "email": user.email, "emailVerified": True,
                          "image": None, "createdAt": now, "updatedAt": now})
        rows.add("account", {"id": sid(org.slug, "account", user.email).hex, "accountId": user_id,
                             "providerId": "credential", "userId": user_id, "password": better_auth_hash(DEMO_PASSWORD),
                             "createdAt": now, "updatedAt": now})
        first, *rest = user.name.split()
        rows.add("organisation_user", {"user_id": user_id, "organisation_id": org_id, "email": user.email,
                                       "display_name": f"{first} {rest[-1][0]}." if rest else first, **ts})
        rows.add("membership", {"id": sid(org.slug, "membership", user.email), "organisation_id": org_id,
                                "user_id": user_id, "site_id": site_ids[user.site_code] if user.site_code else None,
                                "role": user.role, **ts})

    for key, value in org.config.items():
        spec = REGISTRY[key]
        rows.add("config_value", {"id": sid(org.slug, "config", key), "scope": "organisation", "organisation_id": org_id,
                                  "site_id": None, "key": key, "value": spec.dump(spec.validate(value)), "version": 1,
                                  "updated_by": "system:seed", **ts})

    for code, item in cat.ingredients.items():
        rows.add("ingredient", {"id": cat.ingredient_ids[code], "organisation_id": org_id, "code": code,
                                "name": item.name, "category": item.category, "base_unit": item.base_unit,
                                "shelf_life_days": item.shelf_life_days, "storage_area": item.storage_area,
                                "active": True, **ts})
        for unit, factor in item.conversions.items():
            rows.add("unit_conversion", {"id": sid(org.slug, "conv", code, unit), "organisation_id": org_id,
                                         "ingredient_id": cat.ingredient_ids[code], "unit": unit,
                                         "factor_to_base": factor})

    for s in org.suppliers:
        rows.add("supplier", {"id": cat.supplier_ids[s.code], "organisation_id": org_id, "name": s.name,
                              "normalised_name": normalise_name(s.name), "vat_number": s.vat_number,
                              "address": s.address, "email": s.email, "phone": s.phone,
                              "lead_time_days": s.lead_time_days, "delivery_weekdays": list(s.delivery_weekdays),
                              "currency": org.currency, "active": True, **ts})
        for alias in s.aliases:
            rows.add("supplier_alias", {"id": sid(org.slug, "alias", alias), "organisation_id": org_id,
                                        "supplier_id": cat.supplier_ids[s.code], "alias": normalise_name(alias), **ts})
    for p in cat.products.values():
        rows.add("supplier_product", {
            "id": p.id, "organisation_id": org_id, "supplier_id": cat.supplier_ids[p.supplier],
            "ingredient_id": cat.ingredient_ids[p.ingredient], "sku": p.sku, "name": p.name,
            "purchase_unit": p.purchase_unit, "pack_size": p.pack_size, "base_qty_per_unit": p.base_qty_per_unit,
            "moq_units": Decimal(1), "contract_price_minor": None, "contract_valid_until": None,
            "vat_rate": p.vat_rate, "active": True, **ts})

    for site in org.sites:
        for code in org.ingredients:
            rows.add("site_ingredient", {
                "id": sid(org.slug, "site_ingredient", site.code, code), "organisation_id": org_id,
                "site_id": cat.site_id(site), "ingredient_id": cat.ingredient_ids[code],
                "par_level_base": org.par_levels.get(code, Decimal(0)),
                "default_supplier_product_id": cat.default_product(code).id, "active": True, "version": 1, **ts})

    recipe_start = start - timedelta(days=365)
    for mi in org.menu:
        item_id = cat.menu_ids[mi.code]
        rows.add("menu_item", {"id": item_id, "organisation_id": org_id, "code": mi.code, "name": mi.name,
                               "category": mi.category, "active": True, **ts})
        rows.add("external_ref", {"id": sid(org.slug, "extref", mi.code), "organisation_id": org_id,
                                  "provider": "simulator", "entity_type": "menu_item", "entity_id": item_id,
                                  "external_id": f"SIM-{mi.code}", **ts})
        for site in org.sites:
            rows.add("menu_item_price", {
                "id": sid(org.slug, "price", site.code, mi.code), "organisation_id": org_id,
                "site_id": cat.site_id(site), "menu_item_id": item_id, "price_minor": int(mi.price * 100),
                "vat_rate": mi.vat_rate, "effective_from": recipe_start, "effective_to": None, **ts})
        recipe_id = sid(org.slug, "recipe", mi.code, 1)
        rows.add("recipe", {"id": recipe_id, "organisation_id": org_id, "menu_item_id": item_id, "version": 1,
                            "effective_from": recipe_start, "effective_to": None, "yield_portions": 1, **ts})
        for line, use in zip(mi.recipe, cat.recipes[mi.code], strict=True):
            rows.add("recipe_line", {
                "id": sid(org.slug, "recipe_line", mi.code, 1, line.ingredient), "organisation_id": org_id,
                "recipe_id": recipe_id, "ingredient_id": cat.ingredient_ids[line.ingredient],
                "quantity": line.quantity, "unit": line.unit, "waste_factor": line.waste,
                "qty_base_per_portion": use.qty_base_per_portion.quantize(Decimal("0.000001"))})


def normalise_name(name: str) -> str:
    import re

    text = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    text = re.sub(r"\b(ltd|limited|plc|llp|co|the|and)\b", " ", text)
    return " ".join(text.split())


def history_rows(org: OrgProfile, site: SiteSpec, cat: Catalogue, rows: Rows, start: date, end: date
                 ) -> SiteWorld:
    """Run the simulator for one site over [start, end] and collect operational rows."""
    org_id, site_id = cat.org_id, cat.site_id(site)
    world = SiteWorld(org, site, cat, WorldState({}, {}, par=dict(org.par_levels)))
    for m in world.opening_stock(start):
        rows.add("stock_movement", movement_row(org_id, site_id, cat, m))
    dayparts = dayparts_from_config(REGISTRY["site.dayparts"].validate(
        org.config.get("site.dayparts", REGISTRY["site.dayparts"].default)))
    item_ids = {f"SIM-{code}": i for code, i in cat.menu_ids.items()}
    po_status: dict[str, str] = {}
    po_headers: dict[str, tuple[dict, list[dict]]] = {}
    day = start
    while day <= end:
        for ing, old, new, reason in world.apply_par_changes(day):
            rows.add("audit_event", {
                "at": world.at(day, site.opening), "organisation_id": org_id, "site_id": site_id,
                "actor": "user:" + sid(org.slug, "user", org.users[1].email).hex, "entity_type": "site_ingredient",
                "entity_id": str(sid(org.slug, "site_ingredient", site.code, ing)), "action": "par_level_change",
                "before": {"par_level_base": str(old)}, "after": {"par_level_base": str(new), "reason": reason},
                "request_id": None, "job_id": None})
        for delivery in world.deliveries(day):
            for table, data in delivery_rows(org_id, site_id, cat, site, delivery, delivery.wac_after).items():
                rows.add(table, data)
            if delivery.po_id:
                po_status[delivery.po_id] = po_status_after(delivery)
        sales, _ = world.sales(day)
        for sale in sales:
            order, lines = sale_rows(sale, organisation_id=org_id, site_id=site_id, tz=world.tz, dayparts=dayparts,
                                     item_ids=item_ids)
            rows.add("sales_order", order)
            rows.add("sales_order_line", lines)
        rows.add("shift", [shift_row(s, organisation_id=org_id, site_id=site_id) for s in world.shifts(day)])
        rows.add("cash_up", cash_up_row(world.cash_up(day, sales), organisation_id=org_id, site_id=site_id))
        eod = world.end_of_day(day, sales)
        rows.add("stock_movement", [movement_row(org_id, site_id, cat, m) for m in eod.movements])
        rows.add("waste_entry", [waste_row(org_id, site_id, cat, w, day) for w in eod.waste])
        if eod.count:
            header, lines = count_rows(org_id, site_id, cat, eod.count, day)
            rows.add("stock_count", header)
            rows.add("stock_count_line", lines)
        for po in world.place_orders(day):
            po_headers[po.id] = po_rows(org_id, site_id, cat, po, org.currency)
        day += timedelta(days=1)
    for po_id, (header, lines) in po_headers.items():
        header["status"] = po_status.get(po_id, "sent")
        rows.add("purchase_order", header)
        rows.add("purchase_order_line", lines)
    # Alternative suppliers send monthly price lists (S3: Bramley offers chicken thigh at 7.19/kg).
    month = start.replace(day=1)
    while month <= end:
        for (supplier, ingredient), product in cat.products.items():
            if ingredient in cat.suppliers[supplier].alternatives:
                price = cat.price_minor(supplier, ingredient, month)
                rows.add("price_observation", {
                    "id": sid(org.slug, "price_list", site.code, supplier, ingredient, month),
                    "organisation_id": org_id, "site_id": site_id, "supplier_id": cat.supplier_ids[supplier],
                    "supplier_product_id": product.id, "ingredient_id": cat.ingredient_ids[ingredient],
                    "observed_on": max(month, start), "unit_price_minor": price,
                    "price_per_base_minor": (Decimal(price) / product.base_qty_per_unit).quantize(Decimal("0.000001")),
                    "source": "price_list", "source_ref": f"{supplier}:{month:%Y-%m}"})
        month = (month + timedelta(days=32)).replace(day=1)
    for d in (start + timedelta(days=n) for n in range((end - start).days + 15)):
        w = weather(site.city, d)
        rows.add("weather_day", {"id": sid(org.slug, "weather", site.code, d), "organisation_id": org_id,
                                 "site_id": site_id, "day": d, "temp_max_c": w.temp_max, "temp_min_c": w.temp_min,
                                 "precipitation_mm": w.precipitation, "source": w.source,
                                 "created_at": _now(), "updated_at": _now()})
    return world


async def seed_org(conn: psycopg.AsyncConnection, org: OrgProfile, *, days: int = SEED_DAYS,
                   end: date = SEED_END) -> tuple[dict[str, int], dict[str, SiteWorld]]:
    started = time.perf_counter()
    cat = Catalogue(org)
    start = end - timedelta(days=days - 1)
    rows = Rows()
    reference_rows(org, cat, rows, start)
    worlds = {site.code: history_rows(org, site, cat, rows, start, end) for site in org.sites}
    # Par levels as they stand at the end of the history (scenario par changes applied, e.g. S7's 18 kg).
    by_id = {v: k for k, v in cat.ingredient_ids.items()}
    site_codes = {cat.site_id(s): s.code for s in org.sites}
    for row in rows.tables["site_ingredient"]:
        par = worlds[site_codes[row["site_id"]]].state.par.get(by_id[row["ingredient_id"]])
        if par is not None:
            row["par_level_base"] = par
    rows.add("audit_event", {"at": _now(), "organisation_id": cat.org_id, "site_id": None, "actor": "system:seed",
                             "entity_type": "organisation", "entity_id": str(cat.org_id), "action": "seed",
                             "before": None, "after": {"days": days, "end": end.isoformat()},
                             "request_id": None, "job_id": None})
    counts = await copy_rows(conn, rows)
    log.info("seeded %s in %.1fs", org.slug, time.perf_counter() - started)
    return counts, worlds


async def seed_bank_holidays(conn: psycopg.AsyncConnection, region: str) -> None:
    async with conn.cursor() as cur:
        for d, title in holidays(region):
            await cur.execute(
                "INSERT INTO bank_holiday (id, region, day, title) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (sid("bank_holiday", region, d), region, d, title))


def preview_next_day(world: SiteWorld, day: date):
    """Deliveries the simulator will make on `day` (used to render upload-only invoices ahead of time)."""
    clone = SiteWorld(world.org, world.site, world.cat, copy.deepcopy(world.state))
    return clone.deliveries(day)


_ = uuid  # ids are generated by helpers
