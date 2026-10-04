"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { A, Badge, Card, DatePicker, Delta, Empty, ErrorBox, PageHeader, SkeletonPage } from "@/components/ui";
import { api } from "@/lib/api/client";
import { date, label, money, num, pct } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

/** SCR-02 Morning Dashboard: open cases awaiting approval first, KPI cards, money-ranked risks, outcomes. */
export default function Dashboard() {
  const { site, epoch } = useSession();
  const [asOf, setAsOf] = useState<string | null>(null);
  useEffect(() => setAsOf(null), [site?.id, epoch]); // follow the latest day after a site switch or a simulated day
  const dash = useApi(() => api.GET("/api/v1/dashboard", { params: { query: { as_of: asOf } } }), [asOf]);
  const cases = useApi(() => api.GET("/api/v1/cases", { params: { query: { limit: 20 } } }));

  if (dash.loading && !dash.data) return <SkeletonPage />;
  if (dash.error) return <ErrorBox message={dash.error} onRetry={dash.reload} />;
  const d = dash.data!;
  const currency = site?.currency ?? "GBP";
  const open = (cases.data ?? []).filter((c) => c.status !== "closed");

  return (
    <div className="space-y-6">
      <PageHeader title={`Good morning — ${site?.name}`} subtitle={<>{`Trading day ${date(d.business_date)} compared with the same weekday over the last 4 weeks`}{d.business_date !== d.latest_date && <span className="block text-xs">Viewing a past day — open cases, approvals and invoices are current.</span>}</>}
        actions={<DatePicker value={d.business_date} min={d.earliest_date} max={d.latest_date} onChange={(v) => setAsOf(v === d.latest_date ? null : v)} />} />

      <Card title={`Open cases (${open.length})`} actions={<A href="/actions">Action Centre →</A>}>
        {cases.loading && !cases.data ? <div className="skeleton h-20" /> : open.length === 0 ? <Empty>No open cases. OpsPilot will open one when something needs attention.</Empty> : (
          <ul className="divide-y divide-[var(--border)]">
            {open.slice(0, 6).map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <Link href={`/cases/${c.id}`} className="font-medium hover:underline">{c.title}</Link>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                    <Badge value={c.status} /> <Badge value={c.severity} />
                    {c.top_cause && <span>Cause: {c.top_cause} ({num(c.confidence, 2)})</span>}
                  </div>
                </div>
                <div className="text-right text-sm">
                  {(c.pending_approvals ?? 0) > 0 && <div className="font-medium">{c.pending_approvals} awaiting approval</div>}
                  <div className="text-[var(--muted)]">{money(c.expected_impact_minor, currency, 0)} / week at stake</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {d.kpis.map((k) => (
          <div key={k.key} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="text-xs uppercase tracking-wide text-[var(--muted)]">{k.label}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">
              {k.value === null ? "—" : k.unit === "money" ? money(k.value, currency, 0) : k.unit === "pct" ? pct(k.value) : num(k.value)}
            </div>
            <div className="mt-1 text-sm">
              <Delta value={k.delta} unit={k.delta_unit === "pt" ? "pt" : "pct"} goodWhen={k.good_when as "up" | "down"} />
              <span className="ml-1 text-xs text-[var(--muted)]">vs {k.baseline === null ? "—" : k.unit === "money" ? money(k.baseline, currency, 0) : k.unit === "pct" ? pct(k.baseline) : num(k.baseline)}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Risks this week (by money)" className="lg:col-span-2">
          {d.risks.length === 0 ? <Empty>No open risks.</Empty> : (
            <ul className="divide-y divide-[var(--border)] text-sm">
              {d.risks.map((r) => (
                <li key={r.anomaly_id} className="flex items-center justify-between gap-3 py-2">
                  <div>
                    <span className="font-medium">{label(r.detector)}</span>
                    <span className="text-[var(--muted)]"> · {String(r.subject.name ?? label(String(r.subject.type)))} · {date(r.period_end)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="tabular-nums">{money(r.weekly_impact_minor, currency, 0)}/wk</span>
                    <Badge value={r.severity} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-6">
          <Card title="Waiting for you">
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span>Pending approvals</span><span className="font-medium">{d.pending_approvals} · {money(d.pending_impact_minor, currency, 0)}/wk</span></div>
              <div className="flex justify-between"><span>Invoices needing review</span><A href="/invoices">{Object.values(d.invoices_to_review).reduce((a, b) => a + b, 0)}</A></div>
              {Object.entries(d.invoices_to_review).map(([state, n]) => (
                <div key={state} className="flex justify-between pl-3 text-xs text-[var(--muted)]"><span>{label(state)}</span><span>{n}</span></div>
              ))}
            </div>
          </Card>
          <Card title="Outcomes measured">
            {d.outcomes.length === 0 ? <Empty>No outcomes measured yet.</Empty> : (
              <ul className="space-y-2 text-sm">
                {d.outcomes.map((o) => (
                  <li key={o.recommendation_id} className="flex items-start justify-between gap-2">
                    <span>{o.title}<span className="block text-xs text-[var(--muted)]">{label(o.metric)}</span></span>
                    <span className="text-right"><Badge value={o.verdict} />
                      {o.effect_pct !== null && <span className="block text-xs"><Delta value={Number(o.effect_pct)} goodWhen="none" /></span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
