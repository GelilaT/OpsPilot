"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { A, Badge, Card, Delta, Dialog, ErrorBox, PageHeader, SkeletonPage, Stat, usePrompt } from "@/components/ui";
import { api, problemMessage, type Schemas } from "@/lib/api/client";
import { date, dateTime, label, money, num } from "@/lib/format";
import { atLeast, useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

type Rec = Schemas["RecommendationOut"];

const STAGES = [
  { id: "detect", label: "Detect", kinds: ["detected"] },
  { id: "investigate", label: "Investigate", kinds: ["investigated"] },
  { id: "recommend", label: "Recommend", kinds: ["proposed", "adjusted", "superseded"] },
  { id: "approve", label: "Approve", kinds: ["approved", "rejected", "expired"] },
  { id: "execute", label: "Execute", kinds: ["executing", "executed", "failed", "follow_up_scheduled"] },
  { id: "measure", label: "Measure", kinds: ["outcome_measured", "memory_written", "closed"] },
];

/** SCR-10 case view: the agent timeline (detect → … → measure) with evidence, impact formulas, risk and outcome. */
export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const { site, role, bump } = useSession();
  const currency = site?.currency ?? "GBP";
  const detail = useApi(() => api.GET("/api/v1/cases/{case_id}", { params: { path: { case_id: id } } }), [id]);
  const timeline = useApi(() => api.GET("/api/v1/cases/{case_id}/timeline", { params: { path: { case_id: id } } }), [id]);
  const [error, setError] = useState<string | null>(null);
  const prompt = usePrompt();

  if (detail.loading && !detail.data) return <SkeletonPage />;
  if (detail.error) return <ErrorBox message={detail.error} onRetry={detail.reload} />;
  const c = detail.data!;
  const events = timeline.data ?? [];
  const reached = new Set(events.map((e) => e.kind));

  async function refresh() {
    // Execution runs in the worker: refresh now and again shortly after.
    detail.reload();
    timeline.reload();
    setTimeout(() => { detail.reload(); timeline.reload(); bump(); }, 2500);
  }

  async function addNote() {
    const text = await prompt.ask("Add a note to this case", "What should OpsPilot remember?");
    if (!text) return;
    const { error } = await api.POST("/api/v1/notes", { body: { target_type: "case", target_id: id, text } });
    if (error) setError(problemMessage(error));
    else refresh();
  }

  return (
    <div className="space-y-6">
      {prompt.element}
      <PageHeader title={c.title ?? "Case"} subtitle={<span className="flex flex-wrap items-center gap-2"><Badge value={c.status} /><Badge value={c.severity} />
        <span>{label(c.detector)} · opened {dateTime(c.created_at)}</span></span>}
        actions={<>{c.investigation && <A href={`/investigations/${c.investigation.id}`}>Open investigation →</A>}
          <button className="btn-secondary" onClick={addNote}>Add note</button></>} />
      <ErrorBox message={error} />

      <ol className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {STAGES.map((s) => {
          const done = s.kinds.some((k) => reached.has(k));
          return (
            <li key={s.id} className={`rounded-lg border border-[var(--border)] px-3 py-2 text-center text-sm ${done ? "bg-[var(--positive-bg)] font-medium" : "text-[var(--muted)]"}`}>
              {done ? "✓ " : ""}{s.label}
            </li>
          );
        })}
      </ol>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {c.investigation && (
            <Card title="Finding" actions={<span className="text-xs text-[var(--muted)]">investigation v{String(c.investigation.version)}</span>}>
              <p className="text-sm">{String(c.investigation.finding)}</p>
              <ul className="mt-3 space-y-1 text-sm">
                {(c.investigation.causes as { cause_code: string; label: string; confidence: number }[]).map((x) => (
                  <li key={x.cause_code} className="flex items-center gap-3">
                    <div className="h-2 w-32 overflow-hidden rounded-full bg-[var(--chip)]"><div className="h-full bg-[var(--accent)]" style={{ width: `${x.confidence * 100}%` }} /></div>
                    <span className="tabular-nums">{num(x.confidence, 2)}</span><span>{x.label}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <h2 className="text-lg font-semibold">Recommendations</h2>
          {c.recommendations.length === 0 && <p className="text-sm text-[var(--muted)]">No recommendations.</p>}
          {c.recommendations.map((r) => <RecCard key={r.id} rec={r} currency={currency} role={role} onChanged={refresh} onError={setError} />)}
          {c.outcomes.length > 0 && (
            <Card title="Outcomes">
              <ul className="space-y-2 text-sm">
                {c.outcomes.map((o) => (
                  <li key={String(o.recommendation_id)} className="flex flex-wrap items-center gap-3">
                    <Badge value={String(o.verdict)} /> <span>{label(String(o.metric))}</span>
                    <span>counterfactual {num(o.counterfactual as string, 4)} → actual {num(o.actual as string, 4)}</span>
                    {o.effect_pct !== null && <Delta value={Number(o.effect_pct)} goodWhen="none" />}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <div className="space-y-6">
          <Card title="Timeline">
            <ol className="space-y-3 text-sm">
              {events.map((e) => (
                <li key={e.id} className="border-l-2 border-[var(--border)] pl-3">
                  <div className="text-xs text-[var(--muted)]">{dateTime(e.at)} · {e.actor_name ?? e.actor}</div>
                  <div><Badge value={e.kind} tone="neutral" /> {e.summary}</div>
                </li>
              ))}
            </ol>
          </Card>
          {c.memory.length > 0 && (
            <Card title="Remembered">
              {c.memory.map((m) => <p key={String(m.id)} className="text-sm">{String(m.summary)}</p>)}
            </Card>
          )}
          {c.notes.length > 0 && (
            <Card title="Notes">
              <ul className="space-y-2 text-sm">{c.notes.map((n) => <li key={String(n.id)}><span className="text-xs text-[var(--muted)]">{String(n.author)} · {dateTime(String(n.created_at))}</span><br />{String(n.text)}</li>)}</ul>
            </Card>
          )}
          <Card title="Anomaly">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Stat label="Period">{date(String(c.anomaly.period_start))}</Stat>
              <Stat label="Streak">{String(c.anomaly.streak)}</Stat>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function RecCard({ rec: r, currency, role, onChanged, onError }: { rec: Rec; currency: string; role: string | null; onChanged: () => void; onError: (e: string | null) => void }) {
  const [busy, setBusy] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const prompt = usePrompt();
  const canDecide = r.status === "proposed" && atLeast(role, r.required_role);
  const i = r.impact_inputs as Record<string, unknown>;
  const detail = useApi(() => api.GET("/api/v1/actions/{action_id}", { params: { path: { action_id: r.id } } }), [r.id, r.status, r.version]);
  const result = detail.data?.execution?.result as Record<string, unknown> | undefined;

  async function run(fn: () => Promise<{ error?: unknown }>) {
    setBusy(true);
    const { error } = await fn();
    setBusy(false);
    if (error) onError(problemMessage(error));
    else { onError(null); onChanged(); }
  }
  const approve = () => run(() => api.POST("/api/v1/actions/{action_id}/approve", { params: { path: { action_id: r.id }, header: { "if-match": String(r.version) } } }));
  async function reject() {
    const reason = await prompt.ask("Reject recommendation", "Reason (recorded on the case)");
    if (reason) run(() => api.POST("/api/v1/actions/{action_id}/reject", { params: { path: { action_id: r.id }, header: { "if-match": String(r.version) } }, body: { reason } }));
  }

  return (
    <div id={`rec-${r.id}`}>
      {prompt.element}
      <Card title={<span className="flex flex-wrap items-center gap-2">{String(r.parameters.title ?? label(r.type))} <Badge value={r.status} /></span>}
        actions={<span className="text-xs text-[var(--muted)]">v{r.version} · {label(r.type)}</span>}>
        <div className="grid gap-4 sm:grid-cols-4">
          <Stat label="Expected impact" hint="per week">{money(r.expected_impact_minor, currency, 2)}</Stat>
          <Stat label="Confidence">{num(r.confidence, 2)}</Stat>
          <Stat label="Risk">{label(r.risk)}</Stat>
          <Stat label="Approver">{label(r.required_role)}</Stat>
        </div>
        <div className="mt-4 rounded-lg bg-[var(--chip)] p-3 text-sm">
          <div className="text-xs uppercase tracking-wide text-[var(--muted)]">Impact formula</div>
          <div className="font-medium">{String(i.formula ?? "—")}</div>
          <ImpactInputs rec={r} currency={currency} />
        </div>
        {r.notes && <p className="mt-3 whitespace-pre-line text-sm text-[var(--muted)]">{r.notes}</p>}
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-[var(--muted)]">
          <span>Success metric: {label(r.success_metric)}</span>
          {r.follow_up_at && <span>Follow-up {date(r.follow_up_at)}</span>}
          {r.expires_at && r.status === "proposed" && <span>Expires {dateTime(r.expires_at)}</span>}
          {r.approved_by && <span>Approved by {detail.data?.approved_by_name ?? r.approved_by}</span>}
          {r.rejection_reason && <span>Rejected: {r.rejection_reason}</span>}
        </div>
        {result && (
          <div className="mt-3 rounded-lg border border-[var(--border)] p-3 text-sm">
            <div className="text-xs uppercase tracking-wide text-[var(--muted)]">Execution</div>
            {result.po_number ? (
              <p>Purchase order <A href={`/purchase-orders/${String(result.purchase_order_id)}`}>{String(result.po_number)}</A> · <Badge value={String(result.po_status)} />
                {result.emailed_to ? <span> · emailed to {String(result.emailed_to)}</span> : null}</p>
            ) : result.task_id ? <p>Task opened: {String(result.title)}</p>
              : result.par_level_base_to ? <p>Par level {num(Number(result.par_level_base_from) / 1000, 1)} → {num(Number(result.par_level_base_to) / 1000, 1)} kg</p>
                : <pre className="text-xs">{JSON.stringify(result)}</pre>}
          </div>
        )}
        {detail.data?.outcome && (
          <p className="mt-3 text-sm">Outcome: <Badge value={detail.data.outcome.verdict} /> {label(detail.data.outcome.metric)} {detail.data.outcome.effect_pct !== null && <Delta value={Number(detail.data.outcome.effect_pct)} goodWhen="none" />} vs counterfactual</p>
        )}
        {r.status === "proposed" && (
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy || !canDecide} onClick={approve}>Approve</button>
            {(i.adjustable as string[] | undefined)?.length ? <button className="btn-secondary" disabled={busy || !canDecide} onClick={() => setAdjusting(true)}>Adjust</button> : null}
            <button className="btn-secondary" disabled={busy || !canDecide} onClick={reject}>Reject</button>
            {!canDecide && <span className="self-center text-xs text-[var(--muted)]">Needs {label(r.required_role)}</span>}
          </div>
        )}
        <AdjustDialog open={adjusting} rec={r} currency={currency} onClose={() => setAdjusting(false)} onDone={() => { setAdjusting(false); onChanged(); }} onError={onError} />
      </Card>
    </div>
  );
}

function ImpactInputs({ rec: r, currency }: { rec: Rec; currency: string }) {
  const i = r.impact_inputs as Record<string, number | string>;
  if (r.type === "supplier_switch") {
    return <p className="mt-1">{num(i.weekly_qty)} {i.unit}/week × ({money(Number(i.price_from) * 100, currency)} − {money(Number(i.price_to) * 100, currency)}) = <b>{money(r.expected_impact_minor, currency)}</b> · {num(i.saving_pct, 1)}% cheaper · fill rate {num(i.fill_rate_pct)}%</p>;
  }
  if (r.type === "par_level_change") {
    return <p className="mt-1">Par {num(i.par_from, 1)} → {num(i.par_to, 1)} {i.unit} (mean need {num(i.mean_daily_need, 1)} {i.unit}/day × review {num(i.review_period_days, 2)} d + safety {num(i.z, 2)}σ, σ {num(i.sigma_daily, 1)} {i.unit}) · lost GP {money(Number(i.lost_gp_per_event), currency, 0)} per stock-out × {num(i.events_per_week, 2)}/week − holding cost</p>;
  }
  if (r.type === "price_review") {
    return <p className="mt-1">{num(i.weekly_units)} units/week · GP {num(i.current_gp_pct, 1)}% → {num(i.suggested_gp_pct, 1)}% (target {num(i.target_gp_pct, 1)}%) · at −5% volume {money(Number(i.impact_lower_volume_minor), currency)}/week · prices never change automatically</p>;
  }
  return null;
}

function AdjustDialog({ open, rec, currency, onClose, onDone, onError }: { open: boolean; rec: Rec; currency: string; onClose: () => void; onDone: () => void; onError: (e: string | null) => void }) {
  const adjustable = ((rec.impact_inputs as Record<string, unknown>).adjustable as string[] | undefined) ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const describe: Record<string, string> = {
    suggested_gross_minor: `Menu price incl. VAT (pence, current suggestion ${money(Number(rec.parameters.suggested_gross_minor), currency)})`,
    par_level_base: `Par level in grams (now ${num(Number(rec.parameters.par_level_base))})`,
    po_qty_base: `First order quantity in grams (now ${num(Number(rec.parameters.po_qty_base))})`,
    qty_base: `Order quantity in base units (now ${num(Number(rec.parameters.qty_base))})`,
  };
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const parameters = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)]));
    const { error } = await api.POST("/api/v1/actions/{action_id}/adjust", {
      params: { path: { action_id: rec.id }, header: { "if-match": String(rec.version) } }, body: { parameters, note: note || null },
    });
    if (error) onError(problemMessage(error));
    else { onError(null); onDone(); }
  }
  return (
    <Dialog open={open} title="Adjust before approving" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3 text-sm">
        {adjustable.map((k) => (
          <label key={k} className="block">{describe[k] ?? k}
            <input className="input" type="number" value={values[k] ?? ""} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
          </label>
        ))}
        <label className="block">Note<input className="input" value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <p className="text-xs text-[var(--muted)]">The expected impact is recomputed with the same formula and the version increases.</p>
        <div className="flex justify-end gap-2"><button type="button" className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary">Save adjustment</button></div>
      </form>
    </Dialog>
  );
}
