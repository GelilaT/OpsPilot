"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { UserMenu } from "@/components/user-menu";
import { ErrorBox, SkeletonPage } from "@/components/ui";
import { api, problemMessage } from "@/lib/api/client";
import { authClient, clearApiToken, getApiToken } from "@/lib/auth-client";
import { date } from "@/lib/format";
import { SessionProvider, atLeast, useSession } from "@/lib/session";

const NAV = [
  { href: "/", label: "Dashboard", min: "shift_manager" },
  { href: "/actions", label: "Action Centre", min: "shift_manager" },
  { href: "/invoices", label: "Invoices", min: "head_chef" },
  { href: "/suppliers", label: "Suppliers & Prices", min: "general_manager" },
  { href: "/settings", label: "Settings", min: "owner" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <Shell>{children}</Shell>
    </SessionProvider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { me, error, site, role, setSite, epoch } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [businessDate, setBusinessDate] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    if (!site) return;
    api.GET("/api/v1/simulator/state").then(({ data }) => setBusinessDate(data?.enabled ? data.business_date ?? null : null));
  }, [site, epoch]);

  async function signOut() {
    await authClient.signOut();
    clearApiToken();
    router.push("/sign-in");
  }

  const isOwner = me?.org_role === "owner";
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <Link href="/" className="font-semibold tracking-tight">OpsPilot</Link>
          <button className="md:hidden text-sm underline" onClick={() => setMenu(!menu)} aria-expanded={menu}>Menu</button>
          <nav className={`${menu ? "flex" : "hidden"} absolute left-0 right-0 top-full flex-col gap-1 border-b border-[var(--border)] bg-[var(--surface)] p-3 md:static md:flex md:flex-row md:border-0 md:bg-transparent md:p-0`}>
            {NAV.filter((n) => atLeast(role, n.min) || (n.min === "owner" && isOwner)).map((n) => {
              const active = n.href === "/" ? path === "/" : path.startsWith(n.href) || (n.href === "/actions" && (path.startsWith("/cases") || path.startsWith("/investigations")));
              return (
                <Link key={n.href} href={n.href} onClick={() => setMenu(false)}
                  className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-[var(--chip)] font-medium" : "text-[var(--muted)] hover:text-[var(--text)]"}`}>
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {businessDate && (
              <span className="hidden rounded-full bg-[var(--info-bg)] px-2 py-0.5 text-xs text-[var(--info)] sm:inline" title="Simulator business date">
                Business date {date(businessDate)}
              </span>
            )}
            {me && me.sites.length > 0 && (
              <select aria-label="Site" className="input !mt-0 !w-auto !py-1" value={site?.id ?? ""} onChange={(e) => setSite(e.target.value)}>
                {me.sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            )}
            {me && <UserMenu name={me.display_name} role={role} onSignOut={signOut} />}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        {error ? <ErrorBox message={error} /> : !me ? <SkeletonPage /> : !me.organisation ? <Onboard /> : !site ? <SkeletonPage /> : children}
      </main>
    </div>
  );
}

function Onboard() {
  const { reload } = useSession();
  const [name, setName] = useState("");
  const [site, setSite] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const { error } = await api.POST("/api/v1/organisations", {
      body: { name, first_site: { name: site || name, timezone: "Europe/London", currency: "GBP", vat_scheme: "uk_standard", region: "england-and-wales" } },
    });
    setBusy(false);
    if (error) return setError(problemMessage(error));
    await getApiToken(true); // the new organisation and site role arrive in a fresh JWT
    await reload();
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-md space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
      <h1 className="text-xl font-semibold">Set up your organisation</h1>
      <p className="text-sm text-[var(--muted)]">You become its Owner. You can add sites and invite managers in Settings.</p>
      <label className="block text-sm">Business name<input className="input" value={name} onChange={(e) => setName(e.target.value)} required /></label>
      <label className="block text-sm">First site name<input className="input" value={site} onChange={(e) => setSite(e.target.value)} placeholder="e.g. Manchester" /></label>
      {error && <p role="alert" className="text-sm text-[var(--negative)]">{error}</p>}
      <button className="btn-primary" disabled={busy}>{busy ? "Creating…" : "Create organisation"}</button>
    </form>
  );
}
