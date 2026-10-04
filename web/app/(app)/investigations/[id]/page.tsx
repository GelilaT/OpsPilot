"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { A, AiLabel, Badge, Card, ErrorBox, PageHeader, SkeletonPage, usePrompt } from "@/components/ui";
import { api, problemMessage } from "@/lib/api/client";
import { dateTime, label, num } from "@/lib/format";
import { atLeast, useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

type Node = { id: string; kind: string; label: string; status?: string; facts: Record<string, unknown> };
type Narrative = { finding: string; evidence: { node_id: string; text: string }[]; causes: { cause_code: string; text: string }[]; next_action: string };
type Cause = { cause_code: string; label: string; confidence: number; chain: string[]; node_ids: string[] };
type Similar = { memory_id: string; case_id: string | null; date: string; summary: string; score: number; verdict: string | null; entity_overlap: number; cosine: number; recency: number };

/** SCR-09 Investigation: evidence chain, ranked causes, similar past cases, notes. */
export default function InvestigationPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { role } = useSession();
  const inv = useApi(() => api.GET("/api/v1/investigations/{investigation_id}", { params: { path: { investigation_id: id } } }), [id]);
  const notes = useApi(() => api.GET("/api/v1/notes", { params: { query: { target_id: id } } }), [id]);
  const versions = useApi(async () => (inv.data ? api.GET("/api/v1/investigations", { params: { query: { anomaly_id: inv.data.anomaly_id } } }) : { data: [] }), [inv.data?.anomaly_id]);
  const [error, setError] = useState<string | null>(null);
  const [showFacts, setShowFacts] = useState<string | null>(null);
  const prompt = usePrompt();

  if (inv.loading && !inv.data) return <SkeletonPage />;
  if (inv.error) return <ErrorBox message={inv.error} onRetry={inv.reload} />;
  const d = inv.data!;
  const narrative = d.narrative.text as Narrative;
  const causes = (d.narrative.causes ?? []) as Cause[];
  const similar = (d.narrative.similar_cases ?? []) as Similar[];
  const nodes = (d.graph.nodes ?? []) as Node[];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const ruledOut = nodes.filter((n) => n.status === "ruled_out");
  const source = String(d.narrative.source ?? "template");

  async function addNote() {
    const text = await prompt.ask("Add a note", "Context a manager knows that the data does not");
    if (!text) return;
    const { error } = await api.POST("/api/v1/notes", { body: { target_type: "investigation", target_id: id, text } });
    if (error) setError(problemMessage(error));
    else notes.reload();
  }
  async function rerun() {
    const { data, error } = await api.POST("/api/v1/investigations/rerun/{anomaly_id}", { params: { path: { anomaly_id: d.anomaly_id } } });
    if (error) setError(problemMessage(error));
    else router.push(`/investigations/${data.id}`);
  }

  return (
    <div className="space-y-6">
      {prompt.element}
      <PageHeader title="Investigation" subtitle={<span className="flex flex-wrap items-center gap-2">Version {d.version} · {dateTime(d.completed_at)} · <AiLabel source={source} />
        {source === "template" && <span className="text-xs">narrative from the deterministic template</span>}</span>}
        actions={<>
          <button className="btn-secondary" onClick={() => router.back()}>Back</button>
          <button className="btn-secondary" onClick={addNote}>Add note</button>
          {atLeast(role, "general_manager") && <button className="btn-secondary" onClick={rerun} title="Re-run with the data now available; earlier versions are kept">Re-run</button>}
        </>} />
      <ErrorBox message={error} />

      <Card title="Finding">
        <p className="text-base">{narrative.finding}</p>
        <p className="mt-3 text-sm"><span className="font-medium">Next action:</span> {narrative.next_action}</p>
        {(d.narrative.guard_violations as string[] | undefined)?.length ? (
          <p className="mt-2 text-xs text-[var(--warning)]">The AI narrative was rejected by the Number Guard ({(d.narrative.guard_violations as string[]).length} unsupported numbers); the template is shown.</p>
        ) : null}
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Evidence chain" className="lg:col-span-2">
          <ol className="space-y-3">
            {narrative.evidence.map((e, idx) => {
              const n = byId.get(e.node_id);
              return (
                <li key={e.node_id} className="flex gap-3">
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--chip)] text-xs font-medium">{idx + 1}</span>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs uppercase tracking-wide text-[var(--muted)]">{n ? label(n.kind) : e.node_id}</div>
                    <p className="text-sm">{e.text}</p>
                    {n && <button className="text-xs text-[var(--muted)] underline" onClick={() => setShowFacts(showFacts === n.id ? null : n.id)}>{showFacts === n.id ? "Hide facts" : "Show computed facts"}</button>}
                    {showFacts === e.node_id && n && <pre className="mt-1 overflow-x-auto rounded bg-[var(--chip)] p-2 text-xs">{JSON.stringify(n.facts, null, 2)}</pre>}
                  </div>
                </li>
              );
            })}
          </ol>
        </Card>
        <div className="space-y-6">
          <Card title="Possible causes">
            {causes.length === 0 ? <p className="text-sm text-[var(--muted)]">No cause reached 0.30 confidence; a review task was opened.</p> : (
              <ul className="space-y-3 text-sm">
                {causes.map((c) => (
                  <li key={c.cause_code}>
                    <div className="flex items-center justify-between"><span className="font-medium">{c.label}</span><span className="tabular-nums">{num(c.confidence, 2)}</span></div>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-[var(--chip)]"><div className="h-full bg-[var(--accent)]" style={{ width: `${c.confidence * 100}%` }} /></div>
                    <div className="mt-1 text-xs text-[var(--muted)]">Evidence: {c.node_ids.join(", ")}</div>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-[var(--muted)]">confidence = (1 − ∏(1 − w·s)) × timing × (1 − max refuting); hidden below 0.30.</p>
          </Card>
          <Card title="Similar past cases">
            {similar.length === 0 ? <p className="text-sm text-[var(--muted)]">No similar case in the last 365 days (score ≥ 0.5).</p> : (
              <ul className="space-y-3 text-sm">
                {similar.map((s) => (
                  <li key={s.memory_id}>
                    <div className="flex items-center gap-2"><b>{s.date}</b> {s.verdict && <Badge value={s.verdict} />} <span className="text-xs text-[var(--muted)]">score {num(s.score, 2)}</span></div>
                    <p>{s.summary}</p>
                    <p className="text-xs text-[var(--muted)]">entities {num(s.entity_overlap, 2)} · similarity {num(s.cosine, 2)} · recency {num(s.recency, 2)}</p>
                    {s.case_id && <A href={`/cases/${s.case_id}`}>Open case</A>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {ruledOut.length > 0 && (
            <Card title="Ruled out">
              <ul className="space-y-1 text-sm">{ruledOut.map((n) => <li key={n.id}>{n.label}: <span className="text-[var(--muted)]">{Object.entries(n.facts).map(([k, v]) => `${label(k)} ${v}`).join(", ")}</span></li>)}</ul>
            </Card>
          )}
          <Card title="Notes">
            {(notes.data ?? []).length === 0 ? <p className="text-sm text-[var(--muted)]">No notes yet.</p> : (
              <ul className="space-y-2 text-sm">{notes.data!.map((n) => <li key={n.id}><span className="text-xs text-[var(--muted)]">{n.author} · {dateTime(n.created_at)}</span><br />{n.text}</li>)}</ul>
            )}
          </Card>
          {(versions.data ?? []).length > 1 && (
            <Card title="Versions">
              <ul className="space-y-1 text-sm">{versions.data!.map((v) => <li key={v.id}><A href={`/investigations/${v.id}`}>v{v.version}</A> · {num(v.confidence, 2)} · {dateTime(v.created_at)}</li>)}</ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
