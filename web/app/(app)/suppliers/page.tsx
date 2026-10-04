"use client";

import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge, Card, Empty, ErrorBox, PageHeader, Skeleton, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import { date, money, num, pct } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

const SERIES = ["#1f5f4a", "#b45309", "#1d5fa8", "#9333ea", "#be123c", "#0f766e"];

function unitOf(baseUnit: string) {
  return baseUnit === "g" ? { label: "kg", factor: 1000 } : baseUnit === "ml" ? { label: "l", factor: 1000 } : { label: "each", factor: 1 };
}

function isoDaysBefore(d: string, days: number) {
  const x = new Date(`${d}T12:00:00Z`);
  x.setUTCDate(x.getUTCDate() - days);
  return x.toISOString().slice(0, 10);
}

/** SCR-05 Suppliers & Prices: price history charts, supplier comparison, cost attribution waterfall. */
export default function SuppliersPage() {
  const { site } = useSession();
  const currency = site?.currency ?? "GBP";
  const ingredients = useApi(() => api.GET("/api/v1/ingredients"));
  const [ingredientId, setIngredientId] = useState<string>("");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!ingredientId && ingredients.data?.length) {
      const multi = ingredients.data.find((i) => i.code === "chicken_thigh") ?? ingredients.data.find((i) => i.suppliers > 1) ?? ingredients.data[0];
      setIngredientId(multi.id);
    }
  }, [ingredients.data, ingredientId]);

  const ingredient = ingredients.data?.find((i) => i.id === ingredientId);
  const q = filter.trim().toLowerCase();
  const shown = (ingredients.data ?? []).filter((i) =>
    !q || i.name.toLowerCase().includes(q) || i.code.toLowerCase().includes(q));

  return (
    <div className="space-y-6">
      <PageHeader title="Suppliers & Prices" subtitle="Normalised prices per base unit, supplier fill rates and what is driving cost increases." />
      <ErrorBox message={ingredients.error} />
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Card title="Ingredients">
          <input className="input !mt-0 mb-3" placeholder="Search…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Search ingredients" />
          {ingredients.loading && !ingredients.data ? <Skeleton className="h-64" /> : (
            <ul className="max-h-[32rem] space-y-0.5 overflow-y-auto text-sm">
              {shown.length === 0 && <Empty>No ingredients match.</Empty>}
              {shown.map((i) => (
                <li key={i.id}>
                  <button onClick={() => setIngredientId(i.id)} className={`w-full rounded-md px-2 py-1.5 text-left ${i.id === ingredientId ? "bg-[var(--chip)] font-medium" : "hover:bg-[var(--chip)]"}`}>
                    {i.name}
                    <span className="block text-xs text-[var(--muted)]">{i.default_supplier_name ?? "no default"}{i.suppliers > 1 ? ` · ${i.suppliers} suppliers` : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-6">
          {ingredient ? <IngredientView key={ingredient.id} ingredientId={ingredient.id} name={ingredient.name} baseUnit={ingredient.base_unit} currency={currency} /> : <Skeleton className="h-64" />}
        </div>
      </div>
      <Attribution currency={currency} />
    </div>
  );
}

function IngredientView({ ingredientId, name, baseUnit, currency }: { ingredientId: string; name: string; baseUnit: string; currency: string }) {
  const unit = unitOf(baseUnit);
  const cmp = useApi(() => api.GET("/api/v1/procurement/comparison", { params: { query: { ingredient_id: ingredientId } } }), [ingredientId]);
  const [history, setHistory] = useState<Record<string, string | number>[]>([]);
  const [names, setNames] = useState<string[]>([]);

  useEffect(() => {
    if (!cmp.data) return;
    const offers = cmp.data.offers;
    Promise.all(offers.map((o) => api.GET("/api/v1/suppliers/{supplier_id}/prices", { params: { path: { supplier_id: o.supplier_id }, query: { ingredient_id: ingredientId } } })))
      .then((results) => {
        const byDay = new Map<string, Record<string, string | number>>();
        results.forEach((r, idx) => {
          for (const p of r.data ?? []) {
            const row = byDay.get(p.observed_on) ?? { day: p.observed_on };
            row[offers[idx].supplier_name] = (Number(p.price_per_base_minor) * unit.factor) / 100;
            byDay.set(p.observed_on, row);
          }
        });
        setHistory([...byDay.values()].sort((a, b) => String(a.day).localeCompare(String(b.day))));
        setNames(offers.map((o) => o.supplier_name));
      });
  }, [cmp.data, ingredientId, unit.factor]);

  return (
    <>
      <Card title={`${name} — supplier comparison`}>
        {cmp.loading && !cmp.data ? <Skeleton className="h-32" /> : cmp.error ? <ErrorBox message={cmp.error} /> : (
          <>
            <Table head={["Rank", "Supplier", "Product", `Price / ${unit.label}`, "Observed", "Fill rate (90 d)", "Lead time", ""]}>
              {cmp.data!.offers.map((o) => (
                <tr key={o.supplier_product_id} className={o.supplier_id === cmp.data!.switch_to ? "bg-[var(--positive-bg)]" : ""}>
                  <td className="px-3 py-2">{o.rank}</td>
                  <td className="px-3 py-2 font-medium">{o.supplier_name}</td>
                  <td className="px-3 py-2 text-xs">{o.product_name}</td>
                  <td className="px-3 py-2 tabular-nums">{o.price_per_base_minor === null ? "—" : money(Number(o.price_per_base_minor) * unit.factor, currency)}</td>
                  <td className="px-3 py-2 text-xs">{date(o.price_observed_on)}</td>
                  <td className="px-3 py-2 tabular-nums">{o.fill_rate === null ? "—" : pct(Number(o.fill_rate) * 100)}</td>
                  <td className="px-3 py-2">{o.lead_time_days} d</td>
                  <td className="px-3 py-2">{o.is_default && <Badge value="default" tone="neutral" />} {o.supplier_id === cmp.data!.switch_to && <Badge value="switch_candidate" tone="good" />}</td>
                </tr>
              ))}
            </Table>
            {cmp.data!.switch_to && (
              <p className="mt-3 text-sm text-[var(--positive)]">A switch candidate is {num(Number(cmp.data!.switch_saving_pct) * 100, 1)}% cheaper with a fill rate of at least 95% (FR-PRC-10).</p>
            )}
          </>
        )}
      </Card>
      <Card title={`Price history per ${unit.label}`}>
        {history.length === 0 ? <Empty>No price observations.</Empty> : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history} margin={{ left: 8, right: 16, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} minTickGap={24} />
                <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} tickFormatter={(v) => Number(v).toFixed(2)} />
                <Tooltip formatter={(v) => money(Number(v) * 100, currency)} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {names.map((n, i) => <Line key={n} type="stepAfter" dataKey={n} stroke={SERIES[i % SERIES.length]} dot={false} connectNulls strokeWidth={2} isAnimationActive={false} />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
    </>
  );
}

function Attribution({ currency }: { currency: string }) {
  const sim = useApi(() => api.GET("/api/v1/simulator/state"));
  if (sim.loading && !sim.data) return <Skeleton className="h-72" />;
  return <AttributionFor end={sim.data?.business_date ?? new Date().toISOString().slice(0, 10)} currency={currency} />;
}

function AttributionFor({ end, currency }: { end: string; currency: string }) {
  const [days, setDays] = useState(14);
  const start = isoDaysBefore(end, days - 1);
  const attr = useApi(() => api.GET("/api/v1/procurement/cost-attribution", { params: { query: { from: start, to: end } } }), [start, end]);

  const waterfall = useMemo(() => {
    if (!attr.data) return [];
    const top = attr.data.ingredients.slice(0, 8);
    const rest = attr.data.ingredients.slice(8).reduce((s, r) => s + r.delta_cost_minor, 0);
    const steps = [...top.map((r) => ({ name: r.ingredient_name, value: r.delta_cost_minor })), ...(rest ? [{ name: "Others", value: rest }] : [])];
    let running = 0;
    const rows = steps.map((s) => {
      const base = s.value >= 0 ? running : running + s.value;
      running += s.value;
      return { name: s.name, base: base / 100, value: Math.abs(s.value) / 100, positive: s.value >= 0 };
    });
    rows.push({ name: "Total", base: Math.min(0, running) / 100, value: Math.abs(running) / 100, positive: running >= 0 });
    return rows;
  }, [attr.data]);

  return (
    <Card title="Cost increase attribution" actions={
      <select aria-label="Period" className="input !mt-0 !py-1 text-xs" value={days} onChange={(e) => setDays(Number(e.target.value))}>
        <option value={7}>Last 7 days vs prior 7</option><option value={14}>Last 14 days vs prior 14</option><option value={28}>Last 28 days vs prior 28</option>
      </select>}>
      {attr.loading && !attr.data ? <Skeleton className="h-72" /> : attr.error ? <ErrorBox message={attr.error} /> : attr.data!.ingredients.length === 0 ? <Empty>No price changes in this period.</Empty> : (
        <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
          <div className="h-80">
            <p className="mb-2 text-xs text-[var(--muted)]">Δ cost = (current price − previous price) × current usage, {date(attr.data!.current_start)} – {date(attr.data!.current_end)} vs the prior period.</p>
            <ResponsiveContainer width="100%" height="90%">
              <BarChart data={waterfall} margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-25} textAnchor="end" height={70} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v, n) => (n === "base" ? null : money(Number(v) * 100, currency))} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
                <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
                <Bar dataKey="value" stackId="w" isAnimationActive={false}>
                  {waterfall.map((r, i) => <Cell key={i} fill={r.name === "Total" ? "var(--accent)" : r.positive ? "var(--negative)" : "var(--positive)"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div>
            <div className="mb-2 text-sm">Total <b className="tabular-nums">{money(attr.data!.total_delta_minor, currency)}</b></div>
            <Table head={["Supplier", "Δ cost", "Share"]}>
              {attr.data!.suppliers.map((s) => (
                <tr key={s.supplier_id ?? "none"}><td className="px-3 py-1.5">{s.supplier_name ?? "—"}</td>
                  <td className="px-3 py-1.5 tabular-nums">{money(s.delta_cost_minor, currency)}</td><td className="px-3 py-1.5">{pct(Number(s.pct_of_total))}</td></tr>
              ))}
            </Table>
          </div>
        </div>
      )}
    </Card>
  );
}
