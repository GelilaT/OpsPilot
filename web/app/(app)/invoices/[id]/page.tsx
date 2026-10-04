"use client";
/* eslint-disable @next/next/no-img-element -- documents are short-lived signed URLs from the API, not static assets */

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { A, AiLabel, Badge, Card, Delta, ErrorBox, PageHeader, SkeletonPage, Table, usePrompt } from "@/components/ui";
import { api, problemMessage, type Schemas } from "@/lib/api/client";
import { dateTime, label, money, num } from "@/lib/format";
import { useApi } from "@/lib/use-api";

type Detail = Schemas["DocumentDetail"];
type Line = Schemas["LineOut"];
type Exc = Schemas["ExceptionOut"];
const FINAL = new Set(["posted", "rejected", "duplicate", "not_invoice"]);
const PROCESSING = new Set(["received", "classifying", "extracting", "validating", "matching", "approved"]);

/** SCR-04 Invoice Review: document beside extracted fields; lines with match status and price deltas;
 * exceptions with their facts; edit, match, accept, approve or reject. */
export default function Review() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const doc = useApi(() => api.GET("/api/v1/invoices/{document_id}", { params: { path: { document_id: id } } }), [id]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const prompt = usePrompt();

  const state = doc.data?.document.state;
  useEffect(() => {
    if (!state || !PROCESSING.has(state)) return;
    const t = setInterval(() => doc.reload(), 2500);
    return () => clearInterval(t);
  }, [state, doc]);

  if (doc.loading && !doc.data) return <SkeletonPage />;
  if (doc.error) return <ErrorBox message={doc.error} onRetry={doc.reload} />;
  const d = doc.data!;
  const version = String(d.document.version);

  async function act(fn: () => Promise<{ data?: Detail; error?: unknown }>) {
    setBusy(true);
    setError(null);
    const { data, error } = await fn();
    setBusy(false);
    if (error) setError(problemMessage(error));
    else if (data) doc.setData(data);
  }

  const approve = () => act(() => api.POST("/api/v1/invoices/{document_id}/approve", { params: { path: { document_id: id }, header: { "if-match": version } } }));
  const retry = () => act(() => api.POST("/api/v1/invoices/{document_id}/retry", { params: { path: { document_id: id } } }));
  async function reject() {
    const reason = await prompt.ask("Reject invoice", "Why is this invoice rejected?");
    if (reason) act(() => api.POST("/api/v1/invoices/{document_id}/reject", { params: { path: { document_id: id } }, body: { reason } }));
  }
  async function accept(ex: Exc) {
    const note = await prompt.ask(`Accept “${label(ex.code)}”`, "Note explaining why this is acceptable");
    if (note) act(() => api.POST("/api/v1/invoices/{document_id}/exceptions/{exception_id}/accept", { params: { path: { document_id: id, exception_id: ex.id } }, body: { note } }));
  }

  const inv = d.invoice;
  const isImage = d.mime.startsWith("image/");
  const deltas = new Map<string, number>();
  for (const e of d.exceptions) {
    if ((e.code === "price_increase" || e.code === "price_mismatch") && e.line_id && typeof e.facts.change_pct === "number") deltas.set(e.line_id, e.facts.change_pct as number);
  }
  const open = d.exceptions.filter((e) => e.status === "open");

  return (
    <div className="space-y-6">
      {prompt.element}
      <PageHeader title={inv?.number ? `Invoice ${inv.number}` : d.document.filename}
        subtitle={<span className="flex flex-wrap items-center gap-2"><Badge value={d.document.state} /> {d.document.doc_type && <span>{label(d.document.doc_type)}</span>}
          {d.document.confidence && <span>· classification confidence {num(d.document.confidence, 2)}</span>}<AiLabel /> <span>fields extracted by AI; totals recomputed by OpsPilot</span></span>}
        actions={<>
          <button className="btn-secondary" onClick={() => router.push("/invoices")}>Back</button>
          {(d.document.state === "failed" || d.document.state === "needs_review") && <button className="btn-secondary" disabled={busy} onClick={retry}>Retry processing</button>}
          {!["posted", "rejected", "duplicate"].includes(d.document.state) && <button className="btn-danger" disabled={busy} onClick={reject}>Reject</button>}
          {d.approval && d.document.state === "ready_for_approval" && <button className="btn-primary" disabled={busy || !d.approval.can_approve} onClick={approve}
            title={d.approval.can_approve ? "" : `Needs ${label(d.approval.required_role)} and no blocking exceptions`}>Approve & post</button>}
        </>} />
      <ErrorBox message={error} />
      {d.approval && !d.approval.can_approve && d.document.state === "ready_for_approval" && (
        <p className="rounded-lg bg-[var(--warning-bg)] px-4 py-2 text-sm text-[var(--warning)]">Approval requires the {label(d.approval.required_role)} role (you are {label(d.approval.your_role)}).</p>
      )}
      {d.document.duplicate_of_id && <p className="text-sm">Duplicate of <A href={`/invoices/${d.document.duplicate_of_id}`}>the original document</A>.</p>}
      {d.document.failure_reason && <ErrorBox message={d.document.failure_reason} />}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Document">
          {d.file_url ? (isImage && !d.preview_url ? <img src={d.file_url} alt={d.document.filename} className="max-h-[80vh] w-full object-contain" />
            : d.preview_url && d.mime !== "application/pdf" ? <img src={d.preview_url} alt={d.document.filename} className="max-h-[80vh] w-full object-contain" />
              : <iframe src={d.file_url} title={d.document.filename} className="h-[80vh] w-full rounded-md border border-[var(--border)]" />)
            : <p className="text-sm text-[var(--muted)]">File unavailable.</p>}
          <p className="mt-2 text-xs text-[var(--muted)]">Signed link valid for 10 minutes · {d.mime} · {num(d.size_bytes / 1024)} KB{d.pages ? ` · ${d.pages} page(s)` : ""}</p>
        </Card>
        <div className="space-y-6">
          {inv && <HeaderEditor key={`${d.document.version}-${d.document.state}`} detail={d} onSaved={(x) => doc.setData(x)} onError={setError} />}
          <Card title={`Exceptions (${open.length} open)`}>
            {d.exceptions.length === 0 ? <p className="text-sm text-[var(--muted)]">No exceptions — validation passed.</p> : (
              <ul className="space-y-3">
                {d.exceptions.map((e) => (
                  <li key={e.id} className="rounded-lg border border-[var(--border)] p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge value={e.code} tone={e.severity === "critical" ? "critical" : e.severity === "warning" ? "warning" : "info"} />
                      <Badge value={e.status} />
                      {e.blocks_approval && e.status === "open" && <span className="text-xs text-[var(--negative)]">blocks approval</span>}
                      {e.requires_role && <span className="text-xs text-[var(--muted)]">needs {label(e.requires_role)}</span>}
                    </div>
                    <p className="mt-1">{e.message}</p>
                    {e.accepted_note && <p className="mt-1 text-xs text-[var(--muted)]">Accepted by {e.accepted_by}: {e.accepted_note}</p>}
                    {e.status === "open" && !FINAL.has(d.document.state) && <button className="btn-secondary btn-sm mt-2" disabled={busy} onClick={() => accept(e)}>Accept with note</button>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <Card title="Lines">
        <Table head={["#", "Description", "Qty", "Unit price", "Total", "Matched product", "Match", "Base qty", "Price Δ"]}>
          {d.lines.map((l) => <LineRow key={l.id} line={l} delta={deltas.get(l.id)} currency={inv?.currency ?? "GBP"} docId={id} onDone={(x) => doc.setData(x)} onError={setError} />)}
        </Table>
        {inv && (
          <div className="mt-4 flex flex-wrap justify-end gap-6 text-sm">
            <span>Subtotal <b className="tabular-nums">{money(inv.subtotal_minor, inv.currency ?? "GBP")}</b></span>
            <span>VAT <b className="tabular-nums">{money(inv.vat_minor, inv.currency ?? "GBP")}</b></span>
            <span>Total <b className="tabular-nums">{money(inv.total_minor, inv.currency ?? "GBP")}</b>
              {inv.ai_total_minor !== null && inv.ai_total_minor !== inv.total_minor && <span className="ml-1 text-xs text-[var(--warning)]">(AI read {money(inv.ai_total_minor, inv.currency ?? "GBP")})</span>}</span>
          </div>
        )}
      </Card>

      <Card title="History">
        <ul className="space-y-1 text-sm">
          {d.transitions.map((t, i) => (
            <li key={i} className="flex flex-wrap gap-2"><span className="w-36 text-xs text-[var(--muted)]">{dateTime(t.at)}</span>
              <span>{label(t.from_state ?? "—")} → <b>{label(t.to_state)}</b></span><span className="text-[var(--muted)]">{t.actor} · {t.reason}</span></li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function HeaderEditor({ detail, onSaved, onError }: { detail: Detail; onSaved: (d: Detail) => void; onError: (e: string | null) => void }) {
  const inv = detail.invoice!;
  const [form, setForm] = useState({ number: inv.number ?? "", invoice_date: inv.invoice_date ?? "", delivery_date: inv.delivery_date ?? "", po_reference: inv.po_reference ?? "" });
  const [saving, setSaving] = useState(false);
  const editable = !["posted", "rejected", "duplicate"].includes(detail.document.state);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const { data, error } = await api.PATCH("/api/v1/invoices/{document_id}", {
      params: { path: { document_id: detail.document.id }, header: { "if-match": String(detail.document.version) } },
      body: { number: form.number || null, invoice_date: form.invoice_date || null, delivery_date: form.delivery_date || null, po_reference: form.po_reference || null, lines: [] },
    });
    setSaving(false);
    if (error) onError(problemMessage(error));
    else { onError(null); onSaved(data); }
  }
  const field = (k: keyof typeof form, l: string, type = "text") => (
    <label className="block text-sm">{l}<input className="input" type={type} disabled={!editable} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>
  );
  return (
    <Card title="Invoice details" actions={inv.edited && <Badge value="edited" tone="info" />}>
      <form onSubmit={save} className="grid grid-cols-2 gap-3">
        <div className="col-span-2 text-sm">
          <div className="text-xs text-[var(--muted)]">Supplier</div>
          <div className="font-medium">{inv.matched_supplier_name ?? inv.supplier_name ?? "Unknown supplier"}</div>
          {inv.supplier_vat_number && <div className="text-xs text-[var(--muted)]">VAT {inv.supplier_vat_number}</div>}
        </div>
        {field("number", "Invoice number")}
        {field("po_reference", "PO reference")}
        {field("invoice_date", "Invoice date", "date")}
        {field("delivery_date", "Delivery date", "date")}
        {inv.purchase_order_number && <p className="col-span-2 text-xs text-[var(--muted)]">Matched to {inv.purchase_order_number}</p>}
        {editable && <div className="col-span-2 flex justify-end"><button className="btn-secondary" disabled={saving}>{saving ? "Saving…" : "Save and revalidate"}</button></div>}
      </form>
    </Card>
  );
}

function LineRow({ line: l, delta, currency, docId, onDone, onError }: { line: Line; delta?: number; currency: string; docId: string; onDone: (d: Detail) => void; onError: (e: string | null) => void }) {
  const candidates = (l.match_candidates ?? []) as { supplier_product_id: string; name: string; sku: string; score: number }[];
  const unmatched = !l.supplier_product_id && !l.non_stock;
  async function match(productId: string | null, nonStock = false) {
    const { data, error } = await api.POST("/api/v1/invoices/{document_id}/lines/{line_id}/match", {
      params: { path: { document_id: docId, line_id: l.id } }, body: { supplier_product_id: productId, non_stock: nonStock },
    });
    if (error) onError(problemMessage(error));
    else { onError(null); onDone(data); }
  }
  return (
    <tr className={unmatched ? "bg-[var(--warning-bg)]" : ""}>
      <td className="px-3 py-2">{l.line_no}</td>
      <td className="px-3 py-2">{l.raw_description}{l.supplier_sku && <span className="block text-xs text-[var(--muted)]">SKU {l.supplier_sku}</span>}</td>
      <td className="px-3 py-2 tabular-nums">{num(l.quantity, 2)} {l.uom}</td>
      <td className="px-3 py-2 tabular-nums">{l.unit_price_minor === null ? "—" : money(Number(l.unit_price_minor), currency)}</td>
      <td className="px-3 py-2 tabular-nums">{money(l.line_total_minor, currency)}</td>
      <td className="px-3 py-2">
        {l.non_stock ? <span className="text-[var(--muted)]">Non-stock</span> : l.product_name ? (
          <span>{l.product_name}{l.ingredient_name && <span className="block text-xs text-[var(--muted)]">{l.ingredient_name}</span>}</span>
        ) : (
          <div className="flex flex-col gap-1">
            {candidates.map((c) => <button key={c.supplier_product_id} className="btn-secondary btn-sm text-left" onClick={() => match(c.supplier_product_id)}>{c.name} ({num(c.score, 2)})</button>)}
            <button className="text-xs underline" onClick={() => match(null, true)}>Mark non-stock</button>
          </div>
        )}
      </td>
      <td className="px-3 py-2">{l.match_method ? <span className="text-xs">{label(l.match_method)} {l.match_confidence && `· ${num(l.match_confidence, 2)}`}</span> : "—"}</td>
      <td className="px-3 py-2 text-xs tabular-nums">{l.qty_base ? `${num(l.qty_base)} ${l.base_unit ?? ""}` : "—"}</td>
      <td className="px-3 py-2">{delta === undefined ? "—" : <Delta value={delta} goodWhen="down" />}</td>
    </tr>
  );
}
