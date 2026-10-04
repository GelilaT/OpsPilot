"""Recommendation executors (FR-ACT-05, FR-PRC-08), keyed by `recommendation_id:version`.

No external side effect happens before approval: executors run only from the `action.execute` job that
approval enqueues. A replay with the same key returns the recorded result and does nothing.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.audit import record_audit
from app.core.tenancy.context import SiteContext
from app.domain.actions.models import OpsTask, Recommendation, RecommendationExecution
from app.domain.inventory.models import SiteIngredient
from app.domain.purchasing.models import Supplier, SupplierProduct
from app.domain.purchasing.orders import PoLineDraft, can_commit, commit_po, create_draft_po

ZERO = Decimal(0)


def execution_key(rec: Recommendation) -> str:
    return f"{rec.id}:{rec.version}"


async def recorded(ctx: SiteContext, key: str) -> RecommendationExecution | None:
    return (await ctx.session.execute(select(RecommendationExecution).where(
        RecommendationExecution.idempotency_key == key))).scalar_one_or_none()


async def execute(ctx: SiteContext, rec: Recommendation, *, approver_role: str) -> RecommendationExecution:
    key = execution_key(rec)
    existing = await recorded(ctx, key)
    if existing is not None:
        return existing
    fn = EXECUTORS[rec.type]
    result = await fn(ctx, rec, approver_role)
    row = RecommendationExecution(
        organisation_id=ctx.organisation_id, site_id=ctx.site_id, recommendation_id=rec.id,
        recommendation_version=rec.version, executor=fn.__name__, idempotency_key=key, result=result, success=True,
        at=datetime.now(UTC))
    ctx.session.add(row)
    await ctx.session.flush()
    return row


async def _site_ingredient(ctx: SiteContext, ingredient_id: uuid.UUID) -> SiteIngredient:
    return (await ctx.session.execute(select(SiteIngredient).where(
        SiteIngredient.site_id == ctx.site_id, SiteIngredient.ingredient_id == ingredient_id).with_for_update())
            ).scalar_one()


async def supplier_switch(ctx: SiteContext, rec: Recommendation, approver_role: str) -> dict[str, Any]:
    """Change the default supplier, raise a draft PO for the first delivery and commit it when the approver's
    PO limit covers it (the supplier is emailed on commit); otherwise the PO waits for approval."""
    p = rec.parameters
    ingredient_id = uuid.UUID(p["ingredient_id"])
    product = (await ctx.session.execute(select(SupplierProduct).where(
        SupplierProduct.id == uuid.UUID(p["to_supplier_product_id"])))).scalar_one()
    si = await _site_ingredient(ctx, ingredient_id)
    before = str(si.default_supplier_product_id)
    si.default_supplier_product_id = product.id
    si.version += 1
    record_audit(ctx.session, actor=ctx.actor, entity_type="site_ingredient", entity_id=si.id, action="supplier_switch",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id,
                 before={"default_supplier_product_id": before},
                 after={"default_supplier_product_id": str(product.id), "recommendation_id": str(rec.id)})
    result: dict[str, Any] = {"default_supplier_product_id": str(product.id), "previous_supplier_product_id": before}
    qty = Decimal(str(p.get("po_qty_base") or 0))
    if qty > 0:
        supplier = (await ctx.session.execute(select(Supplier).where(Supplier.id == product.supplier_id))).scalar_one()
        po = await create_draft_po(ctx, supplier=supplier, lines=[PoLineDraft(product, qty, ("supplier_switch",
                                                                                               "par_gap"))],
                                   number_ref=f"{rec.id.hex[:8].upper()}-{rec.version}", recommendation_id=rec.id,
                                   notes=f"First order after switching {p.get('from_supplier_name')} → "
                                         f"{supplier.name}")
        result.update({"purchase_order_id": str(po.id), "po_number": po.number, "po_status": po.status,
                       "po_subtotal_minor": po.subtotal_minor})
        limits = ctx.config.get("approval.po_limits").model_dump()
        if can_commit(approver_role, po, limits):
            await commit_po(ctx, po, approver=rec.approved_by or ctx.actor, approver_role=approver_role)
            result.update({"po_status": po.status, "emailed_to": supplier.email})
        else:
            po.status = "pending_approval"
            result["po_status"] = po.status
    return result


async def par_level_change(ctx: SiteContext, rec: Recommendation, approver_role: str) -> dict[str, Any]:
    si = await _site_ingredient(ctx, uuid.UUID(rec.parameters["ingredient_id"]))
    before = float(si.par_level_base)
    si.par_level_base = Decimal(str(rec.parameters["par_level_base"]))
    si.version += 1
    record_audit(ctx.session, actor=ctx.actor, entity_type="site_ingredient", entity_id=si.id, action="par_level_change",
                 organisation_id=ctx.organisation_id, site_id=ctx.site_id, before={"par_level_base": before},
                 after={"par_level_base": float(si.par_level_base), "recommendation_id": str(rec.id)})
    return {"par_level_base_from": before, "par_level_base_to": float(si.par_level_base)}


async def purchase_order(ctx: SiteContext, rec: Recommendation, approver_role: str) -> dict[str, Any]:
    """Draft PO only; it is committed through the purchase-order approval (FR-PRC-08)."""
    product = (await ctx.session.execute(select(SupplierProduct).where(
        SupplierProduct.id == uuid.UUID(rec.parameters["supplier_product_id"])))).scalar_one()
    supplier = (await ctx.session.execute(select(Supplier).where(Supplier.id == product.supplier_id))).scalar_one()
    po = await create_draft_po(ctx, supplier=supplier, lines=[PoLineDraft(
        product, Decimal(str(rec.parameters["qty_base"])), ("stock_out_risk", "safety_stock"))],
        number_ref=f"{rec.id.hex[:8].upper()}-{rec.version}", recommendation_id=rec.id)
    return {"purchase_order_id": str(po.id), "po_number": po.number, "po_status": po.status,
            "po_subtotal_minor": po.subtotal_minor}


async def open_task(ctx: SiteContext, rec: Recommendation, approver_role: str) -> dict[str, Any]:
    """price_review, staffing_change, waste_reduction and investigate_task open a task for the approver role."""
    title = rec.parameters.get("title") or rec.type.replace("_", " ").capitalize()
    detail = rec.notes or ""
    if rec.type == "price_review":
        i = rec.impact_inputs
        detail = (f"Suggested price restores GP to {i.get('suggested_gp_pct')}% (target {i.get('target_gp_pct')}%): "
                  f"+{rec.expected_impact_minor / 100:.2f} per week at current volume, "
                  f"+{int(i.get('impact_lower_volume_minor', 0)) / 100:.2f} at -5% volume. Change the menu price in "
                  f"the POS only after review.")
    task = OpsTask(organisation_id=ctx.organisation_id, site_id=ctx.site_id, recommendation_id=rec.id,
                   title=title[:200], description=detail[:2000] or title, status="open",
                   assignee_role=rec.required_role, due_on=(await ctx.today()) + timedelta(days=3))
    ctx.session.add(task)
    await ctx.session.flush()
    return {"task_id": str(task.id), "title": task.title}


EXECUTORS = {
    "supplier_switch": supplier_switch,
    "par_level_change": par_level_change,
    "purchase_order": purchase_order,
    "price_review": open_task,
    "staffing_change": open_task,
    "waste_reduction": open_task,
    "investigate_task": open_task,
}
