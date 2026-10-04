"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Badge, Card, Dialog, Empty, ErrorBox, PageHeader, Skeleton, Table } from "@/components/ui";
import { api, problemMessage, uploadInvoice } from "@/lib/api/client";
import { date, dateTime, label, money } from "@/lib/format";
import { useApi } from "@/lib/use-api";

const STATE_ORDER = ["needs_review", "ready_for_approval", "received", "classifying", "extracting", "validating", "matching",
  "approved", "posted", "rejected", "duplicate", "not_invoice", "failed"];
const PROCESSING = new Set(["received", "classifying", "extracting", "validating", "matching", "approved"]);
const EXCEPTIONS = ["math_error", "missing_field", "unmatched_unit", "unknown_supplier", "unmatched_line", "price_increase",
  "contract_breach", "qty_mismatch", "price_mismatch", "possible_duplicate", "low_confidence"];

/** SCR-03 Invoice Inbox: documents by state with counts, upload, simulate, filters by supplier and exception. */
export default function Inbox() {
  const [state, setState] = useState<string>("");
  const [supplier, setSupplier] = useState<string>("");
  const [exception, setException] = useState<string>("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [simulateOpen, setSimulateOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const page = useApi(() => api.GET("/api/v1/invoices", {
    params: { query: { state: state || undefined, supplier_id: supplier || undefined, exception: exception || undefined, limit: 100 } },
  }), [state, supplier, exception]);
  const suppliers = useApi(() => api.GET("/api/v1/suppliers"));

  // Documents move through the pipeline in the worker: poll while any is processing.
  const processing = page.data?.items.some((d) => PROCESSING.has(d.state));
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(() => page.reload(), 3000);
    return () => clearInterval(t);
  }, [processing, page]);

  async function onFiles(files: FileList | null) {
    if (!files?.length) return;
    setError(null);
    for (const file of Array.from(files)) {
      const { error } = await uploadInvoice(file);
      if (error) {
        setError(`${file.name}: ${problemMessage(error)}`);
        break;
      }
    }
    setMessage(`${files.length} file(s) uploaded. Processing runs in the background; the list refreshes automatically.`);
    if (fileRef.current) fileRef.current.value = "";
    page.reload();
  }

  const counts = page.data?.counts ?? {};
  return (
    <div className="space-y-6">
      <PageHeader title="Invoice Inbox" subtitle="Upload PDF, JPEG, PNG, WebP or HEIC (up to 20 MB, 10 pages). AI reads them; OpsPilot checks every number."
        actions={<>
          <input ref={fileRef} type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif" className="hidden" onChange={(e) => onFiles(e.target.files)} />
          <button className="btn-primary" onClick={() => fileRef.current?.click()}>Upload invoices</button>
          <button className="btn-secondary" onClick={() => setSimulateOpen(true)}>Simulate invoice</button>
        </>} />
      {message && <p className="rounded-lg bg-[var(--info-bg)] px-4 py-2 text-sm text-[var(--info)]">{message}</p>}
      <ErrorBox message={error} />

      <div className="flex flex-wrap gap-2">
        <button className={`rounded-full px-3 py-1 text-sm ${state === "" ? "bg-[var(--accent)] text-[var(--accent-text)]" : "bg-[var(--chip)]"}`} onClick={() => setState("")}>
          All {Object.values(counts).reduce((a, b) => a + b, 0)}
        </button>
        {STATE_ORDER.filter((s) => counts[s]).map((s) => (
          <button key={s} className={`rounded-full px-3 py-1 text-sm ${state === s ? "bg-[var(--accent)] text-[var(--accent-text)]" : "bg-[var(--chip)]"}`} onClick={() => setState(s)}>
            {label(s)} {counts[s]}
          </button>
        ))}
      </div>

      <Card title="Documents" actions={
        <div className="flex gap-2">
          <select aria-label="Supplier" className="input !mt-0 !py-1 text-xs" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
            <option value="">All suppliers</option>
            {(suppliers.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select aria-label="Exception" className="input !mt-0 !py-1 text-xs" value={exception} onChange={(e) => setException(e.target.value)}>
            <option value="">Any exception</option>
            {EXCEPTIONS.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
        </div>}>
        {page.loading && !page.data ? <Skeleton className="h-48" /> : page.error ? <ErrorBox message={page.error} /> : (
          <Table head={["File", "State", "Supplier", "Invoice", "Date", "Total", "Exceptions", "Uploaded"]}
            empty={page.data!.items.length === 0 && <Empty>No documents. Upload the demo files from demo/invoices.</Empty>}>
            {page.data!.items.map((d) => (
              <tr key={d.id} className="hover:bg-[var(--chip)]">
                <td className="px-3 py-2"><Link href={`/invoices/${d.id}`} className="font-medium text-[var(--accent)] hover:underline">{d.filename}</Link>
                  {d.source === "simulate" && <span className="ml-1 text-xs text-[var(--muted)]">(simulated)</span>}</td>
                <td className="px-3 py-2"><Badge value={d.state} />{PROCESSING.has(d.state) && <span className="ml-1 animate-pulse text-xs">…</span>}</td>
                <td className="px-3 py-2">{d.supplier_name ?? "—"}</td>
                <td className="px-3 py-2">{d.invoice_number ?? "—"}</td>
                <td className="px-3 py-2">{date(d.invoice_date)}</td>
                <td className="px-3 py-2 tabular-nums">{money(d.total_minor, d.currency ?? "GBP")}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">{d.open_exceptions.map((e) => <Badge key={e} value={e} tone={d.blocking ? "warning" : "info"} />)}</div>
                  {d.failure_reason && <div className="text-xs text-[var(--negative)]">{d.failure_reason}</div>}
                </td>
                <td className="px-3 py-2 text-xs text-[var(--muted)]">{dateTime(d.created_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <SimulateDialog open={simulateOpen} onClose={() => setSimulateOpen(false)} suppliers={suppliers.data ?? []}
        onDone={(msg) => { setMessage(msg); page.reload(); }} />
    </div>
  );
}

function SimulateDialog({ open, onClose, suppliers, onDone }: { open: boolean; onClose: () => void; suppliers: { id: string; name: string }[]; onDone: (m: string) => void }) {
  const [supplierId, setSupplierId] = useState("");
  const [change, setChange] = useState("0");
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await api.POST("/api/v1/invoices/simulate", { body: { supplier_id: supplierId || null, price_change_pct: Number(change) } });
    if (error) return setError(problemMessage(error));
    onClose();
    onDone("A simulated invoice was generated and is being processed.");
  }
  return (
    <Dialog open={open} title="Simulate an invoice" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3 text-sm">
        <p className="text-[var(--muted)]">Generates a realistic invoice from the site&apos;s last purchase order and sends it through the same pipeline.</p>
        <label className="block">Supplier
          <select className="input" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
            <option value="">Any</option>
            {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <label className="block">Price change % (e.g. 12 for a +12% increase)
          <input className="input" type="number" step="0.1" value={change} onChange={(e) => setChange(e.target.value)} />
        </label>
        <ErrorBox message={error} />
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary">Generate</button></div>
      </form>
    </Dialog>
  );
}
