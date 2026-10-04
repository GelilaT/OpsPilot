"""Configuration resolved site -> organisation -> system default (FR-TEN-04, FR-SET-01).

Every key is declared once here with its type and system default. Values set by Owners are stored per
scope, versioned and audited. Domain services read configuration only through `SiteContext.config`,
never from constants or restaurant-specific code.
"""

import uuid
from dataclasses import dataclass
from datetime import time
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.audit import record_audit
from app.core.db import Base, Timestamps, UUIDPk
from app.core.errors import Unprocessable

Scope = Literal["system", "organisation", "site"]


class Daypart(BaseModel):
    name: Literal["lunch", "afternoon", "dinner", "late"]
    start: time
    end: time


class Schedules(BaseModel):
    nightly_pipeline: time = time(2, 0)
    outcome_evaluation: time = time(6, 0)
    daily_brief: time = time(7, 0)
    follow_ups: time = time(16, 0)
    weekly_recap_weekday: int = Field(default=0, ge=0, le=6)  # Monday
    weekly_recap: time = time(8, 0)


class RoleLimits(BaseModel):
    """Approval limits in minor units per role; None means unlimited (FR-AUTH-06, FR-INV-15)."""

    shift_manager: int | None = 0
    head_chef: int | None = 50_000
    general_manager: int | None = 500_000
    owner: int | None = None


@dataclass(frozen=True)
class ConfigKey:
    key: str
    type_: Any
    default: Any
    description: str

    def validate(self, value: Any) -> Any:
        try:
            return TypeAdapter(self.type_).validate_python(value)
        except ValidationError as exc:
            raise Unprocessable(f"Invalid value for {self.key}: {exc.errors()[0]['msg']}",
                                code="invalid_config_value") from exc

    def dump(self, value: Any) -> Any:
        return TypeAdapter(self.type_).dump_python(value, mode="json")


_KEYS: list[ConfigKey] = [
    # Invoice intake (FR-INV-04, 08..12)
    ConfigKey("invoice.classification_min_confidence", float, 0.60, "Minimum classifier confidence to continue"),
    ConfigKey("invoice.supplier_name_similarity", float, 0.85, "Trigram similarity to auto-match a supplier"),
    ConfigKey("invoice.line_auto_match", float, 0.85, "Line match score that auto-matches"),
    ConfigKey("invoice.line_suggest_match", float, 0.60, "Line match score that is suggested"),
    ConfigKey("invoice.price_increase_pct", float, 0.05, "Price increase vs last price that raises price_increase"),
    ConfigKey("invoice.price_increase_min_per_unit_minor", int, 5,
              "Minimum absolute increase per kg / l / each (minor units)"),
    ConfigKey("invoice.price_robust_z", float, 3.0, "Robust z-score (MAD) that raises price_increase"),
    ConfigKey("invoice.qty_tolerance_pct", float, 0.02, "Invoiced vs PO/received quantity tolerance"),
    ConfigKey("invoice.price_mismatch_pct", float, 0.01, "Invoiced vs PO price tolerance"),
    ConfigKey("invoice.duplicate_total_tolerance_pct", float, 0.005, "Same supplier+date total tolerance"),
    ConfigKey("invoice.max_future_days", int, 2, "Invoice date may be at most this many days ahead"),
    ConfigKey("invoice.max_age_months", int, 18, "Invoice date may be at most this old"),
    # Approval limits (FR-AUTH-06)
    ConfigKey("approval.invoice_limits", RoleLimits, RoleLimits(), "Invoice approval limit per role"),
    ConfigKey("approval.po_limits", RoleLimits, RoleLimits(), "Purchase order approval limit per role"),
    # Targets
    ConfigKey("targets.food_cost_pct", float, 0.30, "Target food cost % of revenue ex VAT"),
    ConfigKey("targets.labour_pct", float, 0.30, "Target labour % of revenue ex VAT"),
    ConfigKey("targets.gp_pct", float, 0.68, "Target gross profit % per dish"),
    # Detection (FR-ANO-02/04, FR-PRC-02, FR-MNU-05)
    ConfigKey("detection.severity_warning_minor", int, 2_500, "Weekly money impact from which severity is warning"),
    ConfigKey("detection.severity_critical_minor", int, 15_000, "Weekly money impact from which severity is critical"),
    ConfigKey("detection.min_baseline_points", int, 3, "Detectors with fewer baseline points are skipped"),
    ConfigKey("detection.baseline_weeks", int, 4, "Same-weekday baseline length in weeks (median and MAD)"),
    ConfigKey("detection.revenue_drop_pct", float, 0.15, "AR-09: net revenue below baseline by this fraction"),
    ConfigKey("detection.daypart_drop_pct", float, 0.15, "AR-04: daypart revenue below baseline (warning)"),
    ConfigKey("detection.daypart_drop_critical_pct", float, 0.30, "AR-04: daypart revenue below baseline (critical)"),
    ConfigKey("detection.discount_tolerance_pct", float, 0.08, "AR-01: discount rate tolerance"),
    ConfigKey("detection.void_min_minor", int, 2_500, "AR-02: minimum void value for a void spike"),
    ConfigKey("detection.labour_over_points", float, 3.0, "AR-03: labour % over target (warning, points)"),
    ConfigKey("detection.labour_over_critical_points", float, 6.0, "AR-03: labour % over target (critical, points)"),
    ConfigKey("detection.product_decline_ratio", float, 0.70, "AR-05: units below this share of baseline"),
    ConfigKey("detection.product_surge_ratio", float, 1.50, "AR-06: units above this multiple of baseline"),
    ConfigKey("detection.product_min_baseline_units", int, 10, "AR-05/06: minimum baseline units per day"),
    ConfigKey("detection.cash_variance_minor", int, 2_000, "AR-07: cash-up variance threshold (warning)"),
    ConfigKey("detection.cash_variance_critical_minor", int, 5_000, "AR-07: cash-up variance (critical)"),
    ConfigKey("detection.cogs_drift_points", float, 2.0, "AR-08: COGS % above baseline (points)"),
    ConfigKey("detection.price_robust_z", float, 3.0, "Ingredient price robust z-score (90-day MAD)"),
    ConfigKey("detection.high_volume_units_per_week", int, 30, "Items at or above this weekly volume are high-volume"),
    ConfigKey("detection.food_cost_over_points", float, 5.0, "Item food cost % above target by these points"),
    ConfigKey("detection.dismiss_suppress_days", int, 7, "A dismissed fingerprint is suppressed this many days"),
    ConfigKey("investigation.min_cause_confidence", float, 0.30, "Causes below this confidence are hidden"),
    ConfigKey("investigation.low_confidence", float, 0.50, "Top cause below this opens an investigate_task"),
    ConfigKey("detection.cost_increase_pct_30d", float, 0.05, "Ingredient cost increase over 30 days"),
    ConfigKey("detection.margin_decline_points", float, 3.0, "GP % points decline over 28 days"),
    ConfigKey("detection.item_cost_increase_pct_90d", float, 0.08, "Item cost increase over 90 days"),
    ConfigKey("detection.supplier_min_fill_rate", float, 0.95, "Supplier fill rate below this is flagged"),
    # Stock (FR-STK-06)
    ConfigKey("stock.variance_pct", float, 0.05, "Usage variance % flag threshold"),
    ConfigKey("stock.variance_min_minor", int, 1_000, "Usage variance money flag threshold"),
    # Procurement (FR-PRC-10)
    ConfigKey("procurement.switch_min_saving_pct", float, 0.05, "Supplier switch minimum saving"),
    ConfigKey("procurement.switch_min_fill_rate", float, 0.95, "Supplier switch minimum fill rate"),
    ConfigKey("procurement.review_period_days", int, 3, "Order review period"),
    ConfigKey("procurement.service_level_z", float, 1.65, "Safety stock z (95% service level)"),
    # Menu (FR-MNU-06)
    ConfigKey("menu.price_endings", list[int], [95, 50, 0], "Allowed price endings in minor units"),
    # Actions (FR-ACT-02/06)
    ConfigKey("actions.recommendation_expiry_hours", int, 72, "Recommendations expire after"),
    ConfigKey("actions.follow_up_days", int, 7, "Days after execution before the outcome is measured"),
    ConfigKey("actions.pending_nudge_hours", int, 24, "Pending approvals older than this are nudged"),
    ConfigKey("actions.expiry_warning_hours", int, 12, "Recommendations this close to expiry are nudged"),
    # Dayparts and schedules (FR-JOB-05)
    ConfigKey("site.dayparts", list[Daypart], [
        Daypart(name="lunch", start=time(11, 30), end=time(15, 0)),
        Daypart(name="afternoon", start=time(15, 0), end=time(17, 0)),
        Daypart(name="dinner", start=time(17, 0), end=time(21, 30)),
        Daypart(name="late", start=time(21, 30), end=time(23, 59)),
    ], "Trading dayparts in site local time"),
    ConfigKey("site.schedules", Schedules, Schedules(), "Scheduled job times in site local time"),
    ConfigKey("notifications.recipients", list[str], [], "Email recipients for briefs and alerts"),
    # Memory (FR-MEM-06)
    ConfigKey("memory.retention_months", int, 24, "Operational memory retention"),
    # AI (FR-INT-06): the provider and models are chosen per organisation/site on the AI integration
    # connection (settings: model, fallback_models, embedding_model); the prompt version is recorded here.
    ConfigKey("ai.prompt_version", str, "v2", "Prompt and schema version"),
    # Simulation (demo)
    ConfigKey("simulation.enabled", bool, False, "Site runs on the simulator clock (demo)"),
]

REGISTRY: dict[str, ConfigKey] = {k.key: k for k in _KEYS}


class ConfigValue(UUIDPk, Timestamps, Base):
    __tablename__ = "config_value"
    __table_args__ = (
        CheckConstraint("scope IN ('system', 'organisation', 'site')", name="scope_valid"),
        CheckConstraint("(scope = 'system') = (organisation_id IS NULL)", name="system_has_no_org"),
        CheckConstraint("(scope = 'site') = (site_id IS NOT NULL)", name="site_scope_has_site"),
        Index("uq_config_value_scope_key", "scope", "organisation_id", "site_id", "key", unique=True,
              postgresql_nulls_not_distinct=True),
    )

    scope: Mapped[str] = mapped_column(String(16))
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organisation.id", ondelete="CASCADE"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[Any] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(String(120))


@dataclass(frozen=True)
class ResolvedValue:
    key: str
    value: Any
    source: Scope
    version: int | None


class EffectiveConfig:
    """Immutable view of a site's resolved configuration."""

    def __init__(self, values: dict[str, ResolvedValue]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> Any:
        return self._values[key].value

    def get(self, key: str) -> Any:
        if key not in REGISTRY:
            raise KeyError(f"Unknown configuration key {key!r}")
        return self._values[key].value

    def resolved(self) -> dict[str, ResolvedValue]:
        return dict(self._values)


async def resolve_config(session: AsyncSession, organisation_id: uuid.UUID | None,
                         site_id: uuid.UUID | None) -> EffectiveConfig:
    rows = (await session.execute(
        select(ConfigValue).where(
            (ConfigValue.scope == "system")
            | ((ConfigValue.scope == "organisation") & (ConfigValue.organisation_id == organisation_id))
            | ((ConfigValue.scope == "site") & (ConfigValue.site_id == site_id))
        ).execution_options(skip_tenant_filter=True)
    )).scalars().all()
    rank = {"system": 0, "organisation": 1, "site": 2}
    chosen: dict[str, ConfigValue] = {}
    for row in sorted(rows, key=lambda r: rank[r.scope]):
        if row.key in REGISTRY:
            chosen[row.key] = row
    values: dict[str, ResolvedValue] = {}
    for key, spec in REGISTRY.items():
        row = chosen.get(key)
        if row is None:
            values[key] = ResolvedValue(key, spec.default, "system", None)
        else:
            values[key] = ResolvedValue(key, spec.validate(row.value), row.scope, row.version)  # type: ignore[arg-type]
    return EffectiveConfig(values)


async def set_config_value(session: AsyncSession, *, actor: str, scope: Scope, key: str, value: Any,
                           organisation_id: uuid.UUID | None, site_id: uuid.UUID | None = None) -> ConfigValue:
    spec = REGISTRY.get(key)
    if spec is None:
        raise Unprocessable(f"Unknown configuration key {key!r}.", code="unknown_config_key")
    stored = spec.dump(spec.validate(value))
    row = (await session.execute(select(ConfigValue).where(
        ConfigValue.scope == scope, ConfigValue.key == key,
        ConfigValue.organisation_id.is_(None) if organisation_id is None
        else ConfigValue.organisation_id == organisation_id,
        ConfigValue.site_id.is_(None) if site_id is None else ConfigValue.site_id == site_id,
    ).with_for_update())).scalar_one_or_none()
    before = None
    if row is None:
        row = ConfigValue(scope=scope, organisation_id=organisation_id, site_id=site_id, key=key, value=stored,
                          version=1, updated_by=actor)
        session.add(row)
    else:
        before = {"value": row.value, "version": row.version}
        row.value, row.version, row.updated_by = stored, row.version + 1, actor
    await session.flush()
    record_audit(session, actor=actor, entity_type="config_value", entity_id=f"{scope}:{key}", action="set",
                 organisation_id=organisation_id, site_id=site_id, before=before,
                 after={"value": stored, "version": row.version})
    return row


async def clear_config_value(session: AsyncSession, *, actor: str, scope: Scope, key: str,
                             organisation_id: uuid.UUID | None, site_id: uuid.UUID | None = None) -> None:
    row = (await session.execute(select(ConfigValue).where(
        ConfigValue.scope == scope, ConfigValue.key == key, ConfigValue.organisation_id == organisation_id,
        ConfigValue.site_id.is_(None) if site_id is None else ConfigValue.site_id == site_id,
    ))).scalar_one_or_none()
    if row is not None:
        record_audit(session, actor=actor, entity_type="config_value", entity_id=f"{scope}:{key}",
                     action="clear", organisation_id=organisation_id, site_id=site_id,
                     before={"value": row.value, "version": row.version})
        await session.delete(row)

