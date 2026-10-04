"use client";

import { Fragment, useEffect, useState } from "react";

import { Badge, Card, Empty, ErrorBox, PageHeader, Skeleton, Table, Tabs } from "@/components/ui";
import { api, getCurrentSite, problemMessage, type Schemas } from "@/lib/api/client";
import { getApiToken } from "@/lib/auth-client";
import { date, dateTime, label } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useDebounced } from "@/lib/use-debounced";
import { useApi } from "@/lib/use-api";

function matchesFilter(text: string, q: string) {
  const n = q.trim().toLowerCase();
  return !n || text.toLowerCase().includes(n);
}

type Tab = "org" | "members" | "config" | "integrations" | "audit" | "jobs" | "simulator" | "emails";
const ROLES = ["owner", "general_manager", "head_chef", "shift_manager"] as const;

/** SCR-12 Organisation, Settings, Data & Audit (Owner). */
export default function SettingsPage() {
  const { me } = useSession();
  const [tab, setTab] = useState<Tab>("simulator");
  if (me?.org_role !== "owner") return <ErrorBox message="Settings are available to the organisation Owner." />;
  return (
    <div>
      <PageHeader title="Organisation & Settings" subtitle={me.organisation?.name} />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "simulator", label: "Simulator" }, { id: "org", label: "Organisation & sites" }, { id: "members", label: "Members" },
        { id: "config", label: "Configuration" }, { id: "integrations", label: "Integrations" }, { id: "emails", label: "Emails" }, { id: "audit", label: "Audit log" },
        { id: "jobs", label: "Jobs & dead letters" },
      ]} />
      {tab === "simulator" && <Simulator />}
      {tab === "org" && <Sites />}
      {tab === "members" && <Members />}
      {tab === "config" && <Config />}
      {tab === "integrations" && <Integrations />}
      {tab === "emails" && <Emails />}
      {tab === "audit" && <Audit />}
      {tab === "jobs" && <Jobs />}
    </div>
  );
}

function Simulator() {
  const { site, bump } = useSession();
  const state = useApi(() => api.GET("/api/v1/simulator/state"));
  const [scenario, setScenario] = useState("");
  const [run, setRun] = useState<Schemas["JobRunOut"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function nextDay() {
    setBusy(true);
    setError(null);
    const { data, error } = await api.POST("/api/v1/simulator/next-day", { body: { scenario: scenario || null } });
    if (error) {
      setBusy(false);
      return setError(problemMessage(error));
    }
    setRun(data);
    // Poll the job run (FR-API-07) until the worker finishes the day, then give the nightly jobs a moment.
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const res = await api.GET("/api/v1/jobs/runs/{run_id}", { params: { path: { run_id: data.id } } });
      if (res.data) setRun(res.data);
      if (res.data && ["succeeded", "failed"].includes(res.data.status)) break;
    }
    setBusy(false);
    setScenario("");
    state.reload();
    setTimeout(bump, 4000);
  }

  const s = state.data;
  const result = run?.result as Record<string, unknown> | null | undefined;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title={`Simulator — ${site?.name}`}>
        {state.loading && !s ? <Skeleton /> : !s?.enabled ? <Empty>This site is not on the simulator clock.</Empty> : (
          <div className="space-y-3 text-sm">
            <p>Business date <b>{date(s.business_date)}</b>; next simulated day <b>{date(s.next_date)}</b>.</p>
            <p className="text-[var(--muted)]">“Simulate next day” trades one day through the POS port (deliveries, sales, waste, orders, weather), then the worker runs that night&apos;s pipeline, the 06:00 outcome evaluation and the 16:00 follow-ups.</p>
            <label className="block">Check a planted scenario (optional)
              <select className="input" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                <option value="">None</option>
                {Object.entries(s.scenarios).map(([k, v]) => <option key={k} value={k}>{k}: {String(v)}</option>)}
              </select>
            </label>
            <ErrorBox message={error} />
            <button className="btn-primary" disabled={busy} onClick={nextDay}>{busy ? "Simulating…" : "Simulate next day"}</button>
          </div>
        )}
      </Card>
      <Card title="Last run">
        {!run ? <Empty>No run yet in this session.</Empty> : (
          <div className="space-y-2 text-sm">
            <p><Badge value={run.status} /> {run.task} · started {dateTime(run.started_at)}</p>
            {run.error && <ErrorBox message={run.error} />}
            {result && (
              <ul className="space-y-1">
                <li>Business date: <b>{String(result.business_date)}</b> · scenarios {(result.scenarios as string[]).join(", ") || "none"}</li>
                <li>Orders: {String(result.orders)}</li>
                <li>Stock-outs: {Object.entries((result.stock_outs as Record<string, string>) ?? {}).map(([k, v]) => `${label(k)} at ${v}`).join(", ") || "none"}</li>
                <li>Deliveries: {(result.deliveries as { supplier: string; invoice_number: string; booked: boolean }[]).map((d) => `${d.supplier} ${d.invoice_number}${d.booked ? "" : " (awaiting invoice upload)"}`).join("; ") || "none"}</li>
                <li>POs placed: {(result.purchase_orders_placed as string[]).join(", ") || "none"}</li>
              </ul>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

function Sites() {
  const { me, reload } = useSession();
  const sites = useApi(() => api.GET("/api/v1/sites"));
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function add(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await api.POST("/api/v1/sites", { body: { name, timezone: "Europe/London", currency: "GBP", vat_scheme: "uk_standard", region: "england-and-wales" } });
    if (error) return setError(problemMessage(error));
    setName("");
    await getApiToken(true);
    await reload();
    sites.reload();
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Organisation">
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt className="text-[var(--muted)]">Name</dt><dd>{me?.organisation?.name}</dd>
          <dt className="text-[var(--muted)]">Slug</dt><dd>{me?.organisation?.slug}</dd>
          <dt className="text-[var(--muted)]">Currency</dt><dd>{me?.organisation?.default_currency}</dd>
          <dt className="text-[var(--muted)]">Time zone</dt><dd>{me?.organisation?.default_timezone}</dd>
        </dl>
      </Card>
      <Card title="Sites">
        {sites.loading && !sites.data ? <Skeleton /> : (
          <ul className="mb-4 divide-y divide-[var(--border)] text-sm">
            {(sites.data ?? []).map((s) => <li key={s.id} className="py-2"><b>{s.name}</b><span className="block text-xs text-[var(--muted)]">{s.address ?? "—"} · {s.timezone} · {s.currency} · {s.covers ?? "—"} covers</span></li>)}
          </ul>
        )}
        <form onSubmit={add} className="flex gap-2">
          <input className="input !mt-0" placeholder="New site name" value={name} onChange={(e) => setName(e.target.value)} required />
          <button className="btn-primary">Add site</button>
        </form>
        <ErrorBox message={error} />
      </Card>
    </div>
  );
}

function Members() {
  const { me } = useSession();
  const members = useApi(() => api.GET("/api/v1/memberships"));
  const [form, setForm] = useState<{ email: string; role: (typeof ROLES)[number]; site_id: string }>({ email: "", role: "shift_manager", site_id: "" });
  const [error, setError] = useState<string | null>(null);
  const siteName = (id: string | null) => (id ? me?.sites.find((s) => s.id === id)?.name ?? id : "All sites (organisation)");
  async function invite(e: React.FormEvent) {
    e.preventDefault();
    const { error } = await api.POST("/api/v1/memberships", { body: { email: form.email, role: form.role, site_id: form.site_id || null } });
    if (error) return setError(problemMessage(error));
    setError(null);
    setForm({ ...form, email: "" });
    members.reload();
  }
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card title="Members and site roles" className="lg:col-span-2">
        <Table head={["Name", "Email", "Role", "Scope"]}>
          {(members.data ?? []).map((m) => (
            <tr key={m.id}><td className="px-3 py-2">{m.display_name ?? "—"}</td><td className="px-3 py-2">{m.email ?? "—"}</td>
              <td className="px-3 py-2">{label(m.role)}</td><td className="px-3 py-2 text-xs">{siteName(m.site_id)}</td></tr>
          ))}
        </Table>
      </Card>
      <Card title="Invite">
        <form onSubmit={invite} className="space-y-3 text-sm">
          <p className="text-xs text-[var(--muted)]">The person must have signed up with this email; their role applies on their next sign-in.</p>
          <label className="block">Email<input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label className="block">Role<select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as (typeof ROLES)[number] })}>
            {ROLES.map((r) => <option key={r} value={r}>{label(r)}</option>)}</select></label>
          <label className="block">Site<select className="input" value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })}>
            <option value="">All sites (organisation role)</option>{me?.sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <ErrorBox message={error} />
          <button className="btn-primary">Add member</button>
        </form>
      </Card>
    </div>
  );
}

function Config() {
  const { site } = useSession();
  const [scope, setScope] = useState<"organisation" | "site">("site");
  const cfg = useApi(() => api.GET("/api/v1/config", { params: { query: { scope, site_id: scope === "site" ? site?.id : undefined } } }), [scope]);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  async function save(key: string, clear = false) {
    let value: unknown = null;
    if (!clear) {
      try {
        value = JSON.parse(editing[key]);
      } catch {
        return setError(`${key}: enter a JSON value (numbers as 0.65, text in "quotes").`);
      }
    }
    const { data, error } = await api.PUT("/api/v1/config", { params: { query: { scope, site_id: scope === "site" ? site?.id : undefined } }, body: { values: { [key]: value } } });
    if (error) return setError(problemMessage(error));
    setError(null);
    cfg.setData(data);
    setEditing((e) => omit(e, key));
  }

  return (
    <Card title="Configuration (site → organisation → system default)" actions={<div className="flex gap-2">
      <input className="input !mt-0 !py-1 text-xs" placeholder="Filter keys" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <select aria-label="Scope" className="input !mt-0 !py-1 text-xs" value={scope} onChange={(e) => setScope(e.target.value as "organisation" | "site")}>
        <option value="site">This site ({site?.name})</option><option value="organisation">Organisation</option></select></div>}>
      <ErrorBox message={error} />
      {cfg.loading && !cfg.data ? <Skeleton className="h-64" /> : (
        <Table head={["Key", "Value", "Source", ""]}>
          {(cfg.data ?? []).filter((c) => matchesFilter(c.key, filter) || matchesFilter(c.description ?? "", filter)).map((c) => (
            <tr key={c.key}>
              <td className="px-3 py-2"><code className="text-xs">{c.key}</code><span className="block text-xs text-[var(--muted)]">{c.description}</span></td>
              <td className="px-3 py-2">
                {editing[c.key] !== undefined ? (
                  <input className="input !mt-0 font-mono text-xs" value={editing[c.key]} onChange={(e) => setEditing({ ...editing, [c.key]: e.target.value })} />
                ) : <code className="break-all text-xs">{JSON.stringify(c.value)}</code>}
              </td>
              <td className="px-3 py-2"><Badge value={c.source} tone={c.source === scope ? "good" : "neutral"} />{c.version ? <span className="ml-1 text-xs text-[var(--muted)]">v{c.version}</span> : null}</td>
              <td className="whitespace-nowrap px-3 py-2">
                {editing[c.key] !== undefined ? <>
                  <button className="btn-primary btn-sm" onClick={() => save(c.key)}>Save</button>{" "}
                  <button className="btn-secondary btn-sm" onClick={() => setEditing((e) => omit(e, c.key))}>Cancel</button></>
                  : <>
                    <button className="btn-secondary btn-sm" onClick={() => setEditing({ ...editing, [c.key]: JSON.stringify(c.value) })}>Edit</button>{" "}
                    {c.source === scope && <button className="btn-secondary btn-sm" onClick={() => save(c.key, true)} title="Remove the override at this scope">Reset</button>}</>}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function omit(o: Record<string, string>, key: string): Record<string, string> {
  const copy = { ...o };
  delete copy[key];
  return copy;
}

function Integrations() {
  const { me } = useSession();
  const view = useApi(() => api.GET("/api/v1/integrations"));
  const [tests, setTests] = useState<Record<string, Schemas["IntegrationTestResult"]>>({});
  const [form, setForm] = useState({ kind: "mail", provider: "", site_id: "", secret_ref: "", settings: "{}" });
  const [error, setError] = useState<string | null>(null);

  async function test(id: string) {
    const { data, error } = await api.POST("/api/v1/integrations/{connection_id}/test", { params: { path: { connection_id: id } } });
    if (error) return setError(problemMessage(error));
    setTests({ ...tests, [id]: data });
    view.reload();
  }
  async function add(e: React.FormEvent) {
    e.preventDefault();
    let settings: Record<string, unknown>;
    try {
      settings = JSON.parse(form.settings || "{}");
    } catch {
      return setError("Settings must be a JSON object.");
    }
    const { error } = await api.POST("/api/v1/integrations", { body: {
      kind: form.kind as Schemas["IntegrationKind"], provider: form.provider, site_id: form.site_id || null, secret_ref: form.secret_ref || null, settings, enabled: true } });
    if (error) return setError(problemMessage(error));
    setError(null);
    view.reload();
  }
  const v = view.data;
  const providers = v?.available[form.kind] ?? [];
  return (
    <div className="space-y-6">
      <ErrorBox message={error} />
      <Card title="Effective adapters (site → organisation → system default)">
        {!v ? <Skeleton /> : (
          <Table head={["Port", "Scope", "Provider", "From"]}>
            {v.effective.map((e, i) => <tr key={i}><td className="px-3 py-2">{label(e.kind)}</td>
              <td className="px-3 py-2 text-xs">{e.site_id ? me?.sites.find((s) => s.id === e.site_id)?.name : "Organisation"}</td>
              <td className="px-3 py-2">{e.provider}</td><td className="px-3 py-2"><Badge value={e.source} tone="neutral" /></td></tr>)}
          </Table>
        )}
      </Card>
      <Card title="Connections">
        {!v ? <Skeleton /> : v.connections.length === 0 ? <Empty>No connections; system defaults apply.</Empty> : (
          <Table head={["Port", "Provider", "Site", "Secret", "Last test", ""]}>
            {v.connections.map((c) => (
              <tr key={c.id}>
                <td className="px-3 py-2">{label(c.kind)}</td><td className="px-3 py-2">{c.provider}</td>
                <td className="px-3 py-2 text-xs">{c.site_id ? me?.sites.find((s) => s.id === c.site_id)?.name : "All"}</td>
                <td className="px-3 py-2 text-xs">{c.secret_ref ?? "—"}</td>
                <td className="px-3 py-2 text-xs">{tests[c.id] ? <span className={tests[c.id].ok ? "text-[var(--positive)]" : "text-[var(--negative)]"}>{tests[c.id].detail}</span>
                  : c.last_test_status ? `${c.last_test_status} · ${dateTime(c.last_tested_at)}` : "—"}</td>
                <td className="px-3 py-2"><button className="btn-secondary btn-sm" onClick={() => test(c.id)}>Test</button></td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <Card title="Add connection">
        <form onSubmit={add} className="grid gap-3 text-sm sm:grid-cols-2">
          <label>Port<select className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value, provider: "" })}>
            {Object.keys(v?.available ?? {}).map((k) => <option key={k} value={k}>{label(k)}</option>)}</select></label>
          <label>Provider<select className="input" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} required>
            <option value="">Choose…</option>{providers.map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
          <label>Site<select className="input" value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })}>
            <option value="">All sites</option>{me?.sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <label>Secret reference (Secret Manager name or env var)<input className="input" value={form.secret_ref} onChange={(e) => setForm({ ...form, secret_ref: e.target.value })} placeholder="e.g. SENDGRID_API_KEY" /></label>
          <label className="sm:col-span-2">Settings (JSON)<textarea className="input font-mono text-xs" value={form.settings} onChange={(e) => setForm({ ...form, settings: e.target.value })} /></label>
          <div className="sm:col-span-2"><button className="btn-primary">Save connection</button></div>
        </form>
      </Card>
    </div>
  );
}

function Emails() {
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const log = useApi(
    () => api.GET("/api/v1/notifications/deliveries", { params: { query: { q: q || undefined, limit: 50 } } }),
    [q],
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  async function send(kind: "daily" | "weekly") {
    setBusy(kind);
    setError(null);
    const { error } = await api.POST("/api/v1/notifications/briefs/send", { body: { kind } });
    if (error) setError(problemMessage(error));
    setTimeout(() => { log.reload(); setBusy(null); }, 2500); // the worker sends it; give it a moment
  }

  async function previewHtml(id: string) {
    const token = await getApiToken();
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const site = getCurrentSite();
    const res = await fetch(`${base}/api/v1/notifications/deliveries/${id}/html`, {
      headers: { Authorization: `Bearer ${token}`, ...(site ? { "X-Site-Id": site } : {}) },
    });
    const body = await res.text();
    if (!res.ok) {
      return setError(body.includes("no_html") || res.status === 404
        ? "No styled HTML for this send — restart API and worker, then use Send morning brief now again."
        : `Preview failed (${res.status}). Check API URL and sign-in.`);
    }
    if (!body.trim()) return setError("Preview was empty — send a new brief after restarting the worker.");
    setPreview(body);
    setError(null);
  }

  return (
    <Card title="Email briefs" actions={<div className="flex flex-wrap items-center gap-2">
      <input className="input !mt-0 !w-40 !py-1 text-xs" placeholder="Search subject, to…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search emails" />
      <button className="btn-secondary btn-sm" disabled={!!busy} onClick={() => send("daily")}>{busy === "daily" ? "Sending…" : "Send morning brief now"}</button>
      <button className="btn-secondary btn-sm" disabled={!!busy} onClick={() => send("weekly")}>{busy === "weekly" ? "Sending…" : "Send weekly recap now"}</button></div>}>
      <p className="mb-3 text-sm text-[var(--muted)]">Briefs are sent as styled HTML (like the dashboard). Use <strong>Preview</strong> to see the layout; plain text is included for older clients. Recipients come from <code>notifications.recipients</code> (Configuration). <Badge value="logged" /> means the console mail stub — connect SendGrid or Resend under Integrations for real delivery.</p>
      {error && <ErrorBox message={error} />}
      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal>
          <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-lg">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
              <span className="text-sm font-medium">Email preview</span>
              <button type="button" className="btn-secondary btn-sm" onClick={() => setPreview(null)}>Close</button>
            </div>
            <iframe title="Email preview" className="min-h-[70vh] w-full flex-1 bg-white" srcDoc={preview} sandbox="allow-same-origin" />
          </div>
        </div>
      )}
      {log.loading && !log.data ? <Skeleton className="h-40" /> : log.error ? <ErrorBox message={log.error} onRetry={log.reload} /> : (
        <Table head={["When", "Email", "To", "Status", ""]} empty={<Empty>No emails yet.</Empty>}>
          {(log.data ?? []).map((d) => (
            <tr key={d.id}>
              <td className="whitespace-nowrap px-3 py-2 text-xs">{dateTime(d.created_at)}</td>
              <td className="px-3 py-2">{d.subject}<span className="block text-xs text-[var(--muted)]">{label(d.kind)}</span></td>
              <td className="px-3 py-2 text-xs">{d.to.join(", ")}</td>
              <td className="px-3 py-2"><Badge value={d.status} />{d.last_error && <span className="block max-w-xs truncate text-xs text-[var(--negative)]" title={d.last_error}>{d.last_error}</span>}</td>
              <td className="px-3 py-2">{d.has_html ? <button type="button" className="btn-secondary btn-sm" onClick={() => previewHtml(d.id)}>Preview</button> : null}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function Audit() {
  const [entity, setEntity] = useState("");
  const [actor, setActor] = useState("");
  const entityQ = useDebounced(entity);
  const actorQ = useDebounced(actor);
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursors[cursors.length - 1];
  const page = useApi(
    () => api.GET("/api/v1/audit", { params: { query: { entity_type: entityQ || undefined, actor: actorQ || undefined, cursor, limit: 50 } } }),
    [entityQ, actorQ, cursor],
  );
  useEffect(() => setCursors([undefined]), [entityQ, actorQ]);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card title="Audit log" actions={<div className="flex gap-2">
      <input className="input !mt-0 !py-1 text-xs" placeholder="Search entity type…" value={entity} onChange={(e) => { setEntity(e.target.value); setCursors([undefined]); }} />
      <input className="input !mt-0 !py-1 text-xs" placeholder="Search actor name…" value={actor} onChange={(e) => { setActor(e.target.value); setCursors([undefined]); }} /></div>}>
      {page.loading && !page.data ? <Skeleton className="h-64" /> : page.error ? <ErrorBox message={page.error} /> : (
        <>
          <Table head={["When", "Actor", "Entity", "Action", ""]}>
            {page.data!.items.map((a) => (
              <Fragment key={a.id}>
                <tr>
                  <td className="whitespace-nowrap px-3 py-2 text-xs">{dateTime(a.at)}</td><td className="px-3 py-2 text-xs">{a.actor_name ?? a.actor}</td>
                  <td className="px-3 py-2 text-xs">{a.entity_type}<span className="block text-[var(--muted)]">{a.entity_id.slice(0, 12)}</span></td>
                  <td className="px-3 py-2">{a.action}</td>
                  <td className="px-3 py-2"><button className="text-xs underline" onClick={() => setOpen(open === a.id ? null : a.id)}>{open === a.id ? "Hide" : "Diff"}</button></td>
                </tr>
                {open === a.id && <tr><td colSpan={5} className="px-3 py-2"><div className="grid gap-2 sm:grid-cols-2 text-xs">
                  <pre className="overflow-x-auto rounded bg-[var(--negative-bg)] p-2">{JSON.stringify(a.before, null, 2)}</pre>
                  <pre className="overflow-x-auto rounded bg-[var(--positive-bg)] p-2">{JSON.stringify(a.after, null, 2)}</pre></div></td></tr>}
              </Fragment>
            ))}
          </Table>
          <div className="mt-3 flex gap-2">
            <button className="btn-secondary btn-sm" disabled={cursors.length < 2} onClick={() => setCursors(cursors.slice(0, -1))}>Newer</button>
            <button className="btn-secondary btn-sm" disabled={!page.data!.next_cursor} onClick={() => setCursors([...cursors, page.data!.next_cursor ?? undefined])}>Older</button>
          </div>
        </>
      )}
    </Card>
  );
}

function Jobs() {
  const dead = useApi(() => api.GET("/api/v1/jobs/dead-letter"));
  const [msg, setMsg] = useState<string | null>(null);
  async function retry(id: number) {
    const { error } = await api.POST("/api/v1/jobs/{job_id}/retry", { params: { path: { job_id: id } } });
    setMsg(error ? problemMessage(error) : `Job ${id} re-queued.`);
    dead.reload();
  }
  return (
    <Card title="Dead letters (failed jobs after retries)">
      {msg && <p className="mb-2 text-sm">{msg}</p>}
      {dead.loading && !dead.data ? <Skeleton /> : (dead.data ?? []).length === 0 ? <Empty>No failed jobs.</Empty> : (
        <Table head={["Job", "Task", "Attempts", "Failed", "Args", ""]}>
          {dead.data!.map((j) => (
            <tr key={j.id}><td className="px-3 py-2">{j.id}</td><td className="px-3 py-2">{j.task_name}</td><td className="px-3 py-2">{j.attempts}</td>
              <td className="px-3 py-2 text-xs">{dateTime(j.failed_at)}</td><td className="max-w-xs truncate px-3 py-2 text-xs">{JSON.stringify(j.args)}</td>
              <td className="px-3 py-2"><button className="btn-secondary btn-sm" onClick={() => retry(j.id)}>Retry</button></td></tr>
          ))}
        </Table>
      )}
    </Card>
  );
}
