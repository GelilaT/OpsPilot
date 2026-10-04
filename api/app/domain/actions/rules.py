"""Recommendation state chart (FR-ACT-03) and the derived case status (FR-ACT-11). Pure rules, no I/O."""

TRANSITIONS: dict[str, set[str]] = {
    "draft": {"proposed", "superseded"},
    "proposed": {"approved", "rejected", "expired", "superseded"},
    "approved": {"executing"},
    "executing": {"completed", "failed"},
    "completed": {"follow_up"},
    "follow_up": {"outcome_measured"},
    "rejected": set(),
    "expired": set(),
    "superseded": set(),
    "failed": set(),
    "outcome_measured": set(),
}

TERMINAL = {"rejected", "expired", "superseded", "failed", "outcome_measured"}
PENDING = {"draft", "proposed"}

# Approver per recommendation type (Recommendation Types table). purchase_order: Head Chef within the PO
# limit, otherwise the role whose limit covers it (checked at approval).
APPROVER = {
    "purchase_order": "head_chef",
    "supplier_switch": "general_manager",
    "par_level_change": "head_chef",
    "price_review": "owner",
    "staffing_change": "general_manager",
    "waste_reduction": "head_chef",
    "investigate_task": "general_manager",
}

SUCCESS_METRIC = {
    "purchase_order": "stock_out_count",
    "supplier_switch": "cost_per_base_unit",
    "par_level_change": "stock_out_count",
    "price_review": "item_gp_pct",
    "staffing_change": "labour_pct",
    "waste_reduction": "usage_variance",
    "investigate_task": "task_closed",
}


def can_transition(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(src, set())


def derive_case_status(*, investigated: bool, rec_statuses: list[str]) -> str:
    """detected -> investigating -> awaiting_approval -> executing -> monitoring -> closed.

    A case waits for approval while any recommendation is proposed; executes while any is approved or
    executing; monitors while any executed recommendation awaits its outcome; closes when every
    recommendation is terminal (rejected, expired, superseded, failed or measured)."""
    statuses = set(rec_statuses)
    if not investigated:
        return "investigating" if rec_statuses else "detected"
    if not statuses:
        return "investigating"
    if statuses & {"proposed", "draft"}:
        return "awaiting_approval"
    if statuses & {"approved", "executing"}:
        return "executing"
    if statuses & {"completed", "follow_up"}:
        return "monitoring"
    return "closed"
