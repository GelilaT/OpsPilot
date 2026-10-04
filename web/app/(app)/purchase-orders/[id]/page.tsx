"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Badge, Card, ErrorBox, PageHeader, SkeletonPage, Stat, Table } from "@/components/ui";
import { api, problemMessage } from "@/lib/api/client";
import { date, dateTime, label, money, num } from "@/lib/format";
import { useApi } from "@/lib/use-api";

/** Purchase order: lines with reason codes, commit within the approver's limit, supplier email status (FR-PRC-07/08). */
export default function PurchaseOrderPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const po = useApi(() => api.GET("/api/v1/purchase-orders/{po_id}", { params: { path: { po_id: id } } }), [id]);
  const [error, setError] = useState<string | null>(null);

  if (po.loading && !po.data) return <SkeletonPage />;
  if (po.error) return <ErrorBox message={po.error} onRetry={po.reload} />;
  const p = po.data!;

  async function commit() {
    const { data, error } = await api.POST("/api/v1/purchase-orders/{po_id}/approve", { params: { path: { po_id: id }, header: { "if-match": String(p.version) } } });
    if (error) setError(problemMessage(error));
    else { po.setData(data); setTimeout(po.reload, 2500); }
  }

  return (
    <div className="space-y-6">
      <PageHeader title={`Purchase order ${p.number}`} subtitle={<span className="flex items-center gap-2"><Badge value={p.status} /> {p.supplier_name}</span>}
        actions={<>
          <button className="btn-secondary" onClick={() => router.back()}>Back</button>
          {(p.status === "draft" || p.status === "pending_approval") && <button className="btn-primary" onClick={commit}>Approve & send</button>}
        </>} />
      <ErrorBox message={error} />
      <Card>
        <div className="grid gap-4 sm:grid-cols-4">
          <Stat label="Ordered">{date(p.order_date)}</Stat>
          <Stat label="Delivery">{date(p.expected_delivery_date)}</Stat>
          <Stat label="Value (ex VAT)">{money(p.subtotal_minor, p.currency)}</Stat>
          <Stat label="Approved by">{p.approved_by_name ?? p.approved_by ?? "—"}</Stat>
        </div>
      </Card>
      <Card title="Lines">
        <Table head={["Product", "SKU", "Packs", "Base qty", "Unit price", "Total", "Reasons"]}>
          {p.lines.map((l, i) => (
            <tr key={i}>
              <td className="px-3 py-2">{l.product}</td><td className="px-3 py-2 text-xs">{l.sku}</td>
              <td className="px-3 py-2 tabular-nums">{num(l.qty_units)}</td><td className="px-3 py-2 tabular-nums">{num(l.qty_base)}</td>
              <td className="px-3 py-2 tabular-nums">{money(l.unit_price_minor, p.currency)}</td><td className="px-3 py-2 tabular-nums">{money(l.line_total_minor, p.currency)}</td>
              <td className="px-3 py-2 text-xs">{l.reason_codes.map(label).join(", ")}</td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card title="Supplier email">
        {p.emails.length === 0 ? <p className="text-sm text-[var(--muted)]">Not emailed (sent when the order is committed).</p> : (
          <ul className="space-y-1 text-sm">
            {p.emails.map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2"><Badge value={String(e.status)} /> to {(e.to as string[]).join(", ")} · via {String(e.provider ?? "—")} · {dateTime(e.sent_at as string | null)} · attempts {String(e.attempts)}
                {e.error ? <span className="text-[var(--negative)]">{String(e.error)}</span> : null}</li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
