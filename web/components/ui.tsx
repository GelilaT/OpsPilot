"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { date, label, signed } from "@/lib/format";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-[var(--muted)]">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className = "" }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-[var(--border)] bg-[var(--surface)] ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES: Record<string, string> = {
  critical: "bg-[var(--negative-bg)] text-[var(--negative)]",
  warning: "bg-[var(--warning-bg)] text-[var(--warning)]",
  info: "bg-[var(--info-bg)] text-[var(--info)]",
  good: "bg-[var(--positive-bg)] text-[var(--positive)]",
  neutral: "bg-[var(--chip)] text-[var(--muted)]",
};

const STATUS_TONE: Record<string, string> = {
  critical: "critical", warning: "warning", info: "info",
  awaiting_approval: "warning", proposed: "warning", ready_for_approval: "warning", needs_review: "warning",
  executing: "info", approved: "info", investigating: "info", detected: "info", monitoring: "info", follow_up: "info",
  received: "info", classifying: "info", extracting: "info", validating: "info", matching: "info", draft: "neutral",
  pending_approval: "warning",
  completed: "good", posted: "good", committed: "good", improved: "good", outcome_measured: "good", sent: "good",
  logged: "good", accepted: "good", closed: "neutral", open: "warning",
  rejected: "critical", failed: "critical", duplicate: "critical", worsened: "critical", expired: "neutral",
  superseded: "neutral", no_change: "neutral", not_invoice: "neutral", dismissed: "neutral",
};

export function Badge({ value, tone }: { value: string | null | undefined; tone?: keyof typeof TONES }) {
  if (!value) return null;
  const t = tone ?? (STATUS_TONE[value] as keyof typeof TONES) ?? "neutral";
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONES[t]}`}>{label(value)}</span>;
}

/** Signed delta coloured by whether the move is good for the business. */
export function Delta({ value, unit = "pct", goodWhen = "up", decimals = 1, currency }: { value: number | null | undefined; unit?: "pct" | "pt" | "money" | ""; goodWhen?: "up" | "down" | "none"; decimals?: number; currency?: string }) {
  if (value === null || value === undefined) return <span className="text-[var(--muted)]">—</span>;
  const good = goodWhen === "none" || value === 0 ? null : (value > 0) === (goodWhen === "up");
  const cls = good === null ? "text-[var(--muted)]" : good ? "text-[var(--positive)]" : "text-[var(--negative)]";
  return <span className={`tabular-nums font-medium ${cls}`}>{signed(value, unit, decimals, currency)}</span>;
}

/** Marks text written by AI (SRS UI rule): AI explains computed facts, it never owns the numbers. */
export function AiLabel({ source }: { source?: string | null }) {
  if (source === "template") {
    return <span className="inline-flex items-center gap-1 rounded-full bg-[var(--chip)] px-2 py-0.5 text-xs text-[var(--muted)]" title="Written from computed facts by a deterministic template">Template</span>;
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--ai-bg)] px-2 py-0.5 text-xs font-medium text-[var(--ai)]" title="AI-generated from computed facts; every number checked by the Number Guard">
      <span aria-hidden>✦</span> AI
    </span>
  );
}

export function Skeleton({ className = "h-24" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-busy="true" aria-label="Loading" />;
}

export function SkeletonPage() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton /><Skeleton /><Skeleton />
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string | null; onRetry?: () => void }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded-lg border border-[var(--negative)] bg-[var(--negative-bg)] px-4 py-3 text-sm text-[var(--negative)]">
      {message}
      {onRetry && <button className="ml-3 underline" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-6 text-center text-sm text-[var(--muted)]">{children}</p>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div role="tablist" className="mb-4 flex flex-wrap gap-1 border-b border-[var(--border)]">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${value === t.id ? "border-[var(--accent)] font-medium" : "border-transparent text-[var(--muted)] hover:text-[var(--text)]"}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label: l, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-[var(--muted)]">{l}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{children}</div>
      {hint && <div className="text-xs text-[var(--muted)]">{hint}</div>}
    </div>
  );
}

export function Dialog({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} className="w-full max-w-lg rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="text-[var(--muted)]">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** A text prompt dialog for notes and reasons (reject, accept exception, dismiss). */
export function usePrompt() {
  const [state, setState] = useState<{ title: string; placeholder?: string; resolve: (v: string | null) => void } | null>(null);
  const [text, setText] = useState("");
  const ask = (title: string, placeholder?: string) =>
    new Promise<string | null>((resolve) => {
      setText("");
      setState({ title, placeholder, resolve });
    });
  const close = (v: string | null) => {
    state?.resolve(v);
    setState(null);
  };
  const element = (
    <Dialog open={!!state} title={state?.title ?? ""} onClose={() => close(null)}>
      <form onSubmit={(e) => { e.preventDefault(); if (text.trim().length >= 3) close(text.trim()); }} className="space-y-3">
        <textarea className="input min-h-24" autoFocus value={text} placeholder={state?.placeholder} onChange={(e) => setText(e.target.value)} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={() => close(null)}>Cancel</button>
          <button className="btn-primary" disabled={text.trim().length < 3}>Confirm</button>
        </div>
      </form>
    </Dialog>
  );
  return { ask, element };
}

export function Table({ head, children, empty }: { head: React.ReactNode[]; children: React.ReactNode; empty?: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-[var(--muted)]">
          <tr>{head.map((h, i) => <th key={i} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)]">{children}</tbody>
      </table>
      {empty}
    </div>
  );
}

export function A({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className="text-[var(--accent)] hover:underline">{children}</Link>;
}

const iso = (y: number, m: number, d: number) => `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
const shiftDay = (v: string, days: number) => {
  const t = new Date(`${v}T12:00:00Z`);
  t.setUTCDate(t.getUTCDate() + days);
  return t.toISOString().slice(0, 10);
};

/** Calendar dropdown for one ISO day (YYYY-MM-DD), bounded by `min`/`max`, with quick presets. */
export function DatePicker({ value, min, max, onChange }: { value: string; min?: string | null; max: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(() => ({ y: Number(value.slice(0, 4)), m: Number(value.slice(5, 7)) - 1 }));
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const allowed = (v: string) => v <= max && (!min || v >= min);
  const pick = (v: string) => {
    if (!allowed(v)) return;
    onChange(v);
    setOpen(false);
  };
  const toggle = () => {
    if (!open) setView({ y: Number(value.slice(0, 4)), m: Number(value.slice(5, 7)) - 1 });
    setOpen(!open);
  };
  const step = (n: number) => setView(({ y, m }) => {
    const t = new Date(Date.UTC(y, m + n, 1));
    return { y: t.getUTCFullYear(), m: t.getUTCMonth() };
  });

  const first = new Date(Date.UTC(view.y, view.m, 1));
  const lead = (first.getUTCDay() + 6) % 7; // Monday-first
  const count = new Date(Date.UTC(view.y, view.m + 1, 0)).getUTCDate();
  const cells = [...Array(lead).fill(null), ...Array.from({ length: count }, (_, i) => i + 1)];
  const monthStart = iso(view.y, view.m, 1);
  const monthEnd = iso(view.y, view.m, count);
  const presets = [
    { label: "Latest", v: max },
    { label: "Previous day", v: shiftDay(max, -1) },
    { label: "A week earlier", v: shiftDay(max, -7) },
  ];

  return (
    <div ref={ref} className="relative">
      <button type="button" className="input flex items-center gap-2 text-left" aria-haspopup="dialog" aria-expanded={open} onClick={toggle}>
        <span aria-hidden>📅</span>
        <span>{date(value)}</span>
        <span aria-hidden className="text-[var(--muted)]">▾</span>
      </button>
      {open && (
        <div role="dialog" aria-label="Choose a date" className="absolute right-0 z-30 mt-2 w-72 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 shadow-lg">
          <div className="mb-2 flex items-center justify-between">
            <button type="button" className="btn-secondary btn-sm" aria-label="Previous month" disabled={!!min && min > monthStart} onClick={() => step(-1)}>‹</button>
            <span className="text-sm font-medium">{first.toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })}</span>
            <button type="button" className="btn-secondary btn-sm" aria-label="Next month" disabled={max <= monthEnd} onClick={() => step(1)}>›</button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center text-xs text-[var(--muted)]">
            {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((w) => <div key={w}>{w}</div>)}
          </div>
          <div className="mt-1 grid grid-cols-7 gap-1">
            {cells.map((d, i) => {
              if (d === null) return <div key={`b${i}`} />;
              const v = iso(view.y, view.m, d);
              const sel = v === value;
              return (
                <button key={v} type="button" disabled={!allowed(v)} onClick={() => pick(v)} aria-pressed={sel} aria-label={date(v)}
                  className={`h-8 rounded-md text-sm tabular-nums disabled:cursor-not-allowed disabled:opacity-30 ${sel ? "bg-[var(--accent)] font-semibold text-white" : v === max ? "border border-[var(--accent)] hover:bg-[var(--chip)]" : "hover:bg-[var(--chip)]"}`}>
                  {d}
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex flex-wrap gap-2 border-t border-[var(--border)] pt-3">
            {presets.map((p) => (
              <button key={p.label} type="button" className="btn-secondary btn-sm" disabled={!allowed(p.v)} onClick={() => pick(p.v)}>{p.label}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
