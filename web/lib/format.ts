/** Display formatting. Money arrives in minor units; deltas are always signed (SRS UI rules). */

export function money(minor: number | null | undefined, currency = "GBP", decimals = 2): string {
  if (minor === null || minor === undefined) return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(minor / 100);
}

export function num(v: number | string | null | undefined, decimals = 0): string {
  if (v === null || v === undefined || v === "") return "—";
  return Number(v).toLocaleString("en-GB", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** "+3.2%" / "−1.4 pt" with a real minus sign. */
export function signed(v: number | null | undefined, unit: "pct" | "pt" | "money" | "" = "pct", decimals = 1, currency = "GBP"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  const abs = Math.abs(v);
  if (unit === "money") return `${sign}${money(abs, currency)}`;
  const body = abs.toLocaleString("en-GB", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  return `${sign}${body}${unit === "pct" ? "%" : unit === "pt" ? " pt" : ""}`;
}

export function date(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d.length === 10 ? `${d}T12:00:00` : d).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

export function dateTime(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function label(code: string | null | undefined): string {
  if (!code) return "—";
  const s = code.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function pct(v: number | string | null | undefined, decimals = 1): string {
  if (v === null || v === undefined) return "—";
  return `${Number(v).toFixed(decimals)}%`;
}
