"""Import every ORM model so Alembic autogenerate, the API and the worker see the whole schema."""

from app.core.audit import AuditEvent
from app.core.db import Base
from app.core.idempotency import IdempotencyRecord
from app.core.integrations import ExternalRef, IntegrationConnection
from app.core.jobs import JobRun
from app.core.ratelimit import RateBucket
from app.core.schedules import ScheduleRun
from app.core.tenancy.config import ConfigValue
from app.core.tenancy.models import Membership, Organisation, OrganisationUser, Site, SiteClock
from app.domain.actions.models import (
    CaseEvent,
    OperationsCase,
    OpsTask,
    Recommendation,
    RecommendationExecution,
    RecommendationOutcome,
    RecommendationTransition,
)
from app.domain.intelligence.models import Anomaly, Investigation, ItemCostSnapshot
from app.domain.inventory.models import (
    Ingredient,
    SiteIngredient,
    StockCount,
    StockCountLine,
    StockMovement,
    UnitConversion,
    WasteEntry,
)
from app.domain.memory.models import MemoryEntry, Note
from app.domain.menu.models import MenuItem, MenuItemPrice, Recipe, RecipeLine
from app.domain.notifications.models import EmailDelivery
from app.domain.purchasing.invoice_models import (
    AICall,
    Invoice,
    InvoiceDocument,
    InvoiceException,
    InvoiceLine,
    InvoiceTransition,
)
from app.domain.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    LineAlias,
    PriceObservation,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierAlias,
    SupplierProduct,
)
from app.domain.sales.models import BankHoliday, CashUp, SalesOrder, SalesOrderLine, Shift, WeatherDay

__all__ = [
    "AICall",
    "Anomaly",
    "AuditEvent",
    "BankHoliday",
    "Base",
    "CaseEvent",
    "CashUp",
    "ConfigValue",
    "EmailDelivery",
    "ExternalRef",
    "GoodsReceipt",
    "GoodsReceiptLine",
    "IdempotencyRecord",
    "Ingredient",
    "IntegrationConnection",
    "Investigation",
    "Invoice",
    "InvoiceDocument",
    "InvoiceException",
    "InvoiceLine",
    "InvoiceTransition",
    "ItemCostSnapshot",
    "JobRun",
    "LineAlias",
    "Membership",
    "MemoryEntry",
    "MenuItem",
    "MenuItemPrice",
    "Note",
    "OperationsCase",
    "OpsTask",
    "Organisation",
    "OrganisationUser",
    "PriceObservation",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "RateBucket",
    "Recipe",
    "RecipeLine",
    "Recommendation",
    "RecommendationExecution",
    "RecommendationOutcome",
    "RecommendationTransition",
    "SalesOrder",
    "SalesOrderLine",
    "ScheduleRun",
    "Shift",
    "Site",
    "SiteClock",
    "SiteIngredient",
    "StockCount",
    "StockCountLine",
    "StockMovement",
    "Supplier",
    "SupplierAlias",
    "SupplierProduct",
    "UnitConversion",
    "WasteEntry",
    "WeatherDay",
]

# Tables carrying organisation_id that are protected by row-level security (FR-TEN-05).
RLS_TABLES = sorted(
    t.name for t in Base.metadata.sorted_tables
    if "organisation_id" in t.c and t.name not in {"audit_event", "config_value"}
)
