"""Row builders shared by the bulk seed (COPY) and "simulate next day" (INSERT): one mapping, two writers."""

import uuid
from datetime import date
from decimal import Decimal

from app.domain.inventory.rules import money_minor
from app.simulation.catalogue import Catalogue, sid
from app.simulation.profile import SiteSpec
from app.simulation.world import CountRecord, Delivery, Movement, POState, WasteRecord


def movement_row(org_id: uuid.UUID, site_id: uuid.UUID, cat: Catalogue, m: Movement) -> dict:
    return {
        "organisation_id": org_id, "site_id": site_id, "ingredient_id": cat.ingredient_ids[m.ingredient],
        "at": m.at, "business_date": m.business_date, "type": m.type, "qty_base": m.qty_base,
        "unit_cost_minor": m.unit_cost_minor.quantize(Decimal("0.000001")),
        "cost_minor": money_minor(m.qty_base, m.unit_cost_minor), "ref_type": m.ref_type, "ref_id": m.ref_id,
    }


def invoice_id_for(cat: Catalogue, site: SiteSpec, delivery: Delivery) -> uuid.UUID:
    return sid(cat.org.slug, "invoice", site.code, delivery.supplier, delivery.invoice_number)


def receipt_ref(cat: Catalogue, site: SiteSpec, delivery: Delivery) -> str:
    return str(invoice_id_for(cat, site, delivery))


def delivery_rows(org_id: uuid.UUID, site_id: uuid.UUID, cat: Catalogue, site: SiteSpec, delivery: Delivery,
                  wac_after: dict[str, Decimal]) -> dict[str, list[dict]]:
    """Goods receipt (+ lines) always; receipts and price observations only when booked (not upload-only)."""
    gr_id = sid(cat.org.slug, "goods_receipt", site.code, delivery.supplier, delivery.business_date,
                *((delivery.seq,) if delivery.seq else ()))
    out: dict[str, list[dict]] = {"goods_receipt": [], "goods_receipt_line": [], "invoice": [], "invoice_line": [],
                                  "stock_movement": [], "price_observation": []}
    invoice_id = invoice_id_for(cat, site, delivery)
    out["goods_receipt"].append({
        "id": gr_id, "organisation_id": org_id, "site_id": site_id,
        "purchase_order_id": uuid.UUID(delivery.po_id) if delivery.po_id else None,
        "supplier_id": cat.supplier_ids[delivery.supplier], "received_at": delivery.received_at,
        "business_date": delivery.business_date, "received_by": "kitchen", "delivery_note_ref": None,
        "invoice_number": delivery.invoice_number, "invoice_id": None if delivery.upload_only else invoice_id,
    })
    merged: dict[str, tuple[Decimal, Decimal]] = {}
    for line in delivery.lines:
        out["goods_receipt_line"].append({
            "id": sid(cat.org.slug, "gr_line", gr_id, line.ingredient), "organisation_id": org_id,
            "site_id": site_id, "goods_receipt_id": gr_id,
            "purchase_order_line_id": uuid.UUID(line.po_line_id) if line.po_line_id else None,
            "supplier_product_id": uuid.UUID(line.supplier_product_id),
            "ingredient_id": cat.ingredient_ids[line.ingredient], "qty_units": line.delivered_units,
            "qty_base": line.delivered_base,
        })
        if delivery.upload_only or line.delivered_base <= 0:
            continue
        qty, value = merged.get(line.ingredient, (Decimal(0), Decimal(0)))
        merged[line.ingredient] = (qty + line.delivered_base, value + line.delivered_base * line.price_per_base_minor)
        out["price_observation"].append({
            "id": uuid.uuid4(), "organisation_id": org_id, "site_id": site_id,
            "supplier_id": cat.supplier_ids[delivery.supplier], "supplier_product_id": uuid.UUID(line.supplier_product_id),
            "ingredient_id": cat.ingredient_ids[line.ingredient], "observed_on": delivery.business_date,
            "unit_price_minor": line.unit_price_minor,
            "price_per_base_minor": line.price_per_base_minor.quantize(Decimal("0.000001")), "source": "invoice",
            "source_ref": str(invoice_id),
        })
    for ingredient, (qty, value) in merged.items():
        price = value / qty
        out["stock_movement"].append({
            "organisation_id": org_id, "site_id": site_id, "ingredient_id": cat.ingredient_ids[ingredient],
            "at": delivery.received_at, "business_date": delivery.business_date, "type": "receipt", "qty_base": qty,
            "unit_cost_minor": wac_after[ingredient].quantize(Decimal("0.000001")),
            "cost_minor": money_minor(qty, price), "ref_type": "invoice", "ref_id": str(invoice_id),
        })
    if not delivery.upload_only:
        out["invoice"], out["invoice_line"] = invoice_rows(org_id, site_id, cat, delivery, invoice_id, gr_id)
    return out


def invoice_rows(org_id: uuid.UUID, site_id: uuid.UUID, cat: Catalogue, delivery: Delivery, invoice_id: uuid.UUID,
                 gr_id: uuid.UUID) -> tuple[list[dict], list[dict]]:
    """The supplier's invoice for a delivery the simulator booked automatically (already posted)."""
    from datetime import timedelta

    from app.domain.purchasing.invoice_rules import normalise_invoice_number

    spec = cat.suppliers[delivery.supplier]
    lines, by_rate = [], {}
    for n, line in enumerate((x for x in delivery.lines if x.delivered_units > 0), start=1):
        product = cat.products[(delivery.supplier, line.ingredient)]
        total = int(line.delivered_units * line.unit_price_minor)
        by_rate[line.vat_rate] = by_rate.get(line.vat_rate, 0) + total
        lines.append({
            "id": sid(cat.org.slug, "invoice_line", invoice_id, n), "organisation_id": org_id, "site_id": site_id,
            "invoice_id": invoice_id, "line_no": n, "raw_description": product.name, "supplier_sku": product.sku,
            "quantity": line.delivered_units, "uom": product.purchase_unit, "pack_size": product.pack_size,
            "unit_price_minor": Decimal(line.unit_price_minor), "line_total_minor": total, "vat_rate": line.vat_rate,
            "supplier_product_id": product.id, "ingredient_id": cat.ingredient_ids[line.ingredient],
            "qty_base": line.delivered_base, "price_per_base_minor": line.price_per_base_minor.quantize(Decimal("0.000001")),
            "match_confidence": Decimal(1), "match_method": "sku", "match_candidates": None, "non_stock": False,
        })
    subtotal = sum(by_rate.values())
    vat = sum(int((Decimal(base) * rate).to_integral_value()) for rate, base in by_rate.items())
    header = {
        "id": invoice_id, "organisation_id": org_id, "site_id": site_id, "document_id": None, "source": "simulator",
        "status": "posted", "supplier_id": cat.supplier_ids[delivery.supplier], "supplier_name": spec.name,
        "supplier_vat_number": spec.vat_number, "supplier_address": spec.address, "number": delivery.invoice_number,
        "normalised_number": normalise_invoice_number(delivery.invoice_number), "invoice_date": delivery.business_date,
        "delivery_date": delivery.business_date, "due_date": delivery.business_date + timedelta(days=30),
        "po_reference": delivery.po_number, "purchase_order_id": uuid.UUID(delivery.po_id) if delivery.po_id else None,
        "goods_receipt_id": gr_id, "currency": cat.org.currency, "subtotal_minor": subtotal, "vat_minor": vat,
        "total_minor": subtotal + vat, "ai_subtotal_minor": None, "ai_vat_minor": None, "ai_total_minor": None,
        "edited": False, "approved_by": "system:simulator", "approved_role": None, "approved_at": delivery.received_at,
        "rejected_reason": None, "posted_at": delivery.received_at, "version": 1,
    }
    return [header], lines


def po_status_after(delivery: Delivery) -> str:
    short = any(line.delivered_units < line.ordered_units for line in delivery.lines)
    return "part_received" if short else "received"


def po_rows(org_id: uuid.UUID, site_id: uuid.UUID, cat: Catalogue, po: POState, currency: str,
            status: str = "sent") -> tuple[dict, list[dict]]:
    lines = [{
        "id": uuid.UUID(line.id), "organisation_id": org_id, "site_id": site_id, "purchase_order_id": uuid.UUID(po.id),
        "supplier_product_id": uuid.UUID(line.supplier_product_id), "ingredient_id": cat.ingredient_ids[line.ingredient],
        "qty_units": line.qty_units, "qty_base": line.qty_base, "unit_price_minor": line.unit_price_minor,
        "line_total_minor": int(line.qty_units * line.unit_price_minor), "reason_codes": ["par_level"],
    } for line in po.lines]
    header = {
        "id": uuid.UUID(po.id), "organisation_id": org_id, "site_id": site_id, "number": po.number,
        "supplier_id": cat.supplier_ids[po.supplier], "status": status, "order_date": po.order_date,
        "expected_delivery_date": po.delivery_date, "currency": currency,
        "subtotal_minor": sum(line["line_total_minor"] for line in lines), "created_by": "kitchen",
        "approved_by": "kitchen", "recommendation_id": None, "notes": None, "version": 1,
    }
    return header, lines


def waste_row(org_id: uuid.UUID, site_id: uuid.UUID, cat: Catalogue, w: WasteRecord, day: date) -> dict:
    return {"id": uuid.uuid4(), "organisation_id": org_id, "site_id": site_id,
            "ingredient_id": cat.ingredient_ids[w.ingredient], "at": w.at, "business_date": day,
            "qty_base": w.qty_base, "reason": w.reason, "cost_minor": w.cost_minor, "recorded_by": "kitchen",
            "note": w.note}


def count_rows(org_id: uuid.UUID, site_id: uuid.UUID, cat: Catalogue, c: CountRecord, day: date
               ) -> tuple[dict, list[dict]]:
    count_id = uuid.uuid4()
    header = {"id": count_id, "organisation_id": org_id, "site_id": site_id, "counted_at": c.counted_at,
              "business_date": day, "storage_area": None, "status": "posted", "counted_by": "kitchen"}
    lines = [{"id": uuid.uuid4(), "organisation_id": org_id, "site_id": site_id, "count_id": count_id,
              "ingredient_id": cat.ingredient_ids[ing], "counted_qty_base": counted, "ledger_qty_base": ledger,
              "adjustment_qty_base": counted - ledger} for ing, counted, ledger in c.lines]
    return header, lines
