"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { authClient, clearApiToken } from "@/lib/auth-client";

/** SCR-01 Sign-in: Better Auth email/password (FR-AUTH-01). */
export default function SignInPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    clearApiToken();
    const res =
      mode === "sign-in"
        ? await authClient.signIn.email({ email, password })
        : await authClient.signUp.email({ email, password, name });
    setBusy(false);
    if (res.error) {
      setError(res.error.message ?? "Sign-in failed. Check your email and password.");
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <main className="relative min-h-screen flex items-center justify-center px-4 bg-[var(--bg)]">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
        <div>
          <h1 className="text-xl font-semibold">OpsPilot</h1>
          <p className="text-sm text-[var(--muted)]">
            {mode === "sign-in" ? "Sign in to your restaurant operations." : "Create your account."}
          </p>
        </div>
        {mode === "sign-up" && (
          <label className="block text-sm">
            Full name
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
          </label>
        )}
        <label className="block text-sm">
          Email
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label className="block text-sm">
          Password
          <span className="relative mt-1 block">
            <input
              className="input mt-0 pr-16"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={10}
              autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
            />
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-xs font-medium text-[var(--muted)] hover:text-[var(--text)]"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </span>
        </label>
        {error && (
          <p role="alert" className="text-sm text-[var(--negative)]">
            {error}
          </p>
        )}
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "Please wait…" : mode === "sign-in" ? "Sign in" : "Create account"}
        </button>
        <button
          type="button"
          className="w-full text-sm text-[var(--muted)] underline"
          onClick={() => setMode(mode === "sign-in" ? "sign-up" : "sign-in")}
        >
          {mode === "sign-in" ? "New to OpsPilot? Create an account" : "Already have an account? Sign in"}
        </button>
      </form>
    </main>
  );
}
