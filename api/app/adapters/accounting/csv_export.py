"""AccountingPort: CSV export for the accountant (Xero/QuickBooks/Sage adapters can replace it)."""

import csv
import io
from datetime import date
from decimal import Decimal

from app.ports.accounting import ExportInvoice, ExportResult

HEADERS = ["invoice_id", "supplier", "supplier_vat_number", "invoice_number", "invoice_date", "due_date",
           "currency", "line_description", "quantity", "unit_price", "line_total", "vat_rate", "account_code",
           "invoice_subtotal", "invoice_vat", "invoice_total"]


def _m(minor: int) -> str:
    return f"{Decimal(minor) / 100:.2f}"


class CsvAccounting:
    provider = "csv"

    def _rows(self, inv: ExportInvoice) -> list[list[str]]:
        return [[inv.invoice_id, inv.supplier_name, inv.supplier_vat_number or "", inv.number,
                 inv.invoice_date.isoformat(), inv.due_date.isoformat() if inv.due_date else "", inv.currency,
                 line.description, f"{line.quantity:f}", _m(line.unit_price_minor), _m(line.line_total_minor),
                 f"{line.vat_rate:f}", line.account_code or "", _m(inv.subtotal_minor), _m(inv.vat_minor),
                 _m(inv.total_minor)] for line in inv.lines]

    def _csv(self, invoices: list[ExportInvoice]) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(HEADERS)
        for inv in invoices:
            writer.writerows(self._rows(inv))
        return buf.getvalue().encode()

    async def export_invoice(self, invoice: ExportInvoice) -> ExportResult:
        return ExportResult(self.provider, f"invoice-{invoice.number}.csv", "text/csv", self._csv([invoice]),
                            len(invoice.lines))

    async def export_period(self, invoices: list[ExportInvoice], start: date, end: date) -> ExportResult:
        return ExportResult(self.provider, f"invoices-{start.isoformat()}-{end.isoformat()}.csv", "text/csv",
                            self._csv(invoices), sum(len(i.lines) for i in invoices))
