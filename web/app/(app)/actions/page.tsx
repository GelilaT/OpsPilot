"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Card, Empty, ErrorBox, PageHeader, Skeleton, Table, Tabs, usePrompt } from "@/components/ui";
import { api } from "@/lib/api/client";
import { dateTime, label, money, num } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

const TYPES = ["supplier_switch", "par_level_change", "price_review", "purchase_order", "waste_reduction", "staffing_change", "investigate_task"];

/** SCR-10 Action Centre: open cases and pending approvals ranked by impact x confidence. */
export default function ActionCentre() {
  const { site } = useSession();
  const currency = site?.currency ?? "GBP";
  const [tab, setTab] = useState<"cases" | "queue" | "tasks">("cases");
  const [caseStatus, setCaseStatus] = useState("awaiting_approval,executing,investigating,detected,monitoring");
  const [recStatus, setRecStatus] = useState("proposed");
  const [type, setType] = useState("");
  const cases = useApi(() => api.GET("/api/v1/cases", { params: { query: { status: caseStatus || undefined, limit: 100 } } }), [caseStatus]);
  const queue = useApi(() => api.GET("/api/v1/actions", { params: { query: { status: recStatus || undefined, type: type || undefined } } }), [recStatus, type]);
  const tasks = useApi(() => api.GET("/api/v1/tasks", { params: { query: { status: "open" } } }));

  return (
    <div className="space-y-6">
      <PageHeader title="Action Centre" subtitle="Detect → investigate → recommend → approve → execute → measure. Approval is the only step that needs you." />
      <Tabs tabs={[{ id: "cases", label: "Cases" }, { id: "queue", label: "Recommendations" }, { id: "tasks", label: `Tasks${tasks.data ? ` (${tasks.data.length})` : ""}` }]} value={tab} onChange={setTab} />

      {tab === "cases" && (
        <Card title="Operations cases" actions={
          <select aria-label="Case status" className="input !mt-0 !py-1 text-xs" value={caseStatus} onChange={(e) => setCaseStatus(e.target.value)}>
            <option value="awaiting_approval,executing,investigating,detected,monitoring">Open</option>
            <option value="awaiting_approval">Awaiting approval</option><option value="monitoring">Monitoring</option>
            <option value="closed">Closed</option><option value="">All</option>
          </select>}>
          {cases.loading && !cases.data ? <Skeleton className="h-40" /> : cases.error ? <ErrorBox message={cases.error} /> : cases.data!.length === 0 ? <Empty>No cases.</Empty> : (
            <ul className="divide-y divide-[var(--border)]">
              {cases.data!.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <Link href={`/cases/${c.id}`} className="font-medium hover:underline">{c.title}</Link>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                      <Badge value={c.status} /> <Badge value={c.severity} /> <span>{label(c.detector)}</span>
                      {c.top_cause && <span>· {c.top_cause} ({num(c.confidence, 2)})</span>}
                      <span>· updated {dateTime(c.updated_at)}</span>
                    </div>
                  </div>
                  <div className="text-right text-sm">
                    {(c.pending_approvals ?? 0) > 0 && <div className="font-medium text-[var(--warning)]">{c.pending_approvals} to approve</div>}
                    <div className="text-[var(--muted)]">{money(c.expected_impact_minor, currency, 0)}/week</div>
                    {c.closed_reason && <div className="text-xs text-[var(--muted)]">{c.closed_reason}</div>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === "queue" && (
        <Card title="Recommendations (impact × confidence)" actions={<div className="flex gap-2">
          <select aria-label="Status" className="input !mt-0 !py-1 text-xs" value={recStatus} onChange={(e) => setRecStatus(e.target.value)}>
            <option value="proposed">Proposed</option><option value="approved,executing">Executing</option><option value="follow_up">Follow-up</option>
            <option value="outcome_measured">Measured</option><option value="rejected,expired,superseded,failed">Closed</option><option value="">All</option>
          </select>
          <select aria-label="Type" className="input !mt-0 !py-1 text-xs" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>{TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select></div>}>
          {queue.loading && !queue.data ? <Skeleton className="h-40" /> : queue.error ? <ErrorBox message={queue.error} /> : (
            <Table head={["Recommendation", "Type", "Impact / week", "Confidence", "Score", "Approver", "Status", "Expires"]} empty={queue.data!.length === 0 && <Empty>Nothing here.</Empty>}>
              {queue.data!.map((r) => (
                <tr key={r.id}>
                  <td className="px-3 py-2"><Link href={`/cases/${r.case_id}#rec-${r.id}`} className="font-medium text-[var(--accent)] hover:underline">{String(r.parameters.title ?? label(r.type))}</Link></td>
                  <td className="px-3 py-2 text-xs">{label(r.type)}</td>
                  <td className="px-3 py-2 tabular-nums">{money(r.expected_impact_minor, currency, 0)}</td>
                  <td className="px-3 py-2 tabular-nums">{num(r.confidence, 2)}</td>
                  <td className="px-3 py-2 tabular-nums">{money(r.queue_score, currency, 0)}</td>
                  <td className="px-3 py-2 text-xs">{label(r.required_role)}</td>
                  <td className="px-3 py-2"><Badge value={r.status} /></td>
                  <td className="px-3 py-2 text-xs">{dateTime(r.expires_at)}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {tab === "tasks" && <TaskList tasks={tasks.data} loading={tasks.loading} error={tasks.error} reload={tasks.reload} />}
    </div>
  );
}

function TaskList({ tasks, loading, error, reload }: { tasks: { id: string; title: string; description: string; assignee_role: string; due_on: string | null }[] | null; loading: boolean; error: string | null; reload: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const prompt = usePrompt();
  async function close(id: string) {
    const note = await prompt.ask("Close task", "What was done?");
    if (!note) return;
    setBusy(id);
    await api.POST("/api/v1/tasks/{task_id}/close", { params: { path: { task_id: id } }, body: { note } });
    setBusy(null);
    reload();
  }
  return (
    <Card title="Open tasks">
      {prompt.element}
      {loading && !tasks ? <Skeleton className="h-32" /> : error ? <ErrorBox message={error} /> : !tasks?.length ? <Empty>No open tasks.</Empty> : (
        <ul className="divide-y divide-[var(--border)]">
          {tasks.map((t) => (
            <li key={t.id} className="flex items-start justify-between gap-3 py-3 text-sm">
              <div><div className="font-medium">{t.title}</div><p className="text-[var(--muted)]">{t.description}</p>
                <span className="text-xs text-[var(--muted)]">For {label(t.assignee_role)}{t.due_on ? ` · due ${t.due_on}` : ""}</span></div>
              <button className="btn-secondary btn-sm" disabled={busy === t.id} onClick={() => close(t.id)}>Close task</button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
