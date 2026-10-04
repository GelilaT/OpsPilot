"""AccountingPort: invoice and period export for the accountant (CSV in v1; Xero/QuickBooks later)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ExportInvoiceLine:
    description: str
    quantity: Decimal
    unit_price_minor: int
    line_total_minor: int
    vat_rate: Decimal
    account_code: str | None = None


@dataclass(frozen=True)
class ExportInvoice:
    invoice_id: str
    supplier_name: str
    supplier_vat_number: str | None
    number: str
    invoice_date: date
    due_date: date | None
    currency: str
    subtotal_minor: int
    vat_minor: int
    total_minor: int
    lines: tuple[ExportInvoiceLine, ...]


@dataclass(frozen=True)
class ExportResult:
    provider: str
    filename: str
    content_type: str
    content: bytes
    records: int
    external_ids: tuple[str, ...] = ()


@runtime_checkable
class AccountingPort(Protocol):
    provider: str

    async def export_invoice(self, invoice: ExportInvoice) -> ExportResult: ...

    async def export_period(self, invoices: list[ExportInvoice], start: date, end: date) -> ExportResult: ...
