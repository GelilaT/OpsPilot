"use client";

import { useEffect, useState } from "react";

import { applyTheme, cycleTheme, getStoredTheme, setTheme, type ThemePreference } from "@/lib/theme";

const LABEL: Record<ThemePreference, string> = { light: "Light", dark: "Dark", system: "System" };

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    applyTheme(getStoredTheme());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (getStoredTheme() === "system") applyTheme("system");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return children;
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [pref, setPref] = useState<ThemePreference>("system");

  useEffect(() => setPref(getStoredTheme()), []);

  return (
    <button
      type="button"
      className={`text-sm underline ${className}`}
      onClick={() => {
        const next = cycleTheme(pref);
        setTheme(next);
        setPref(next);
      }}
      aria-label={`Theme: ${LABEL[pref]}. Click to change.`}
      title={`Theme: ${LABEL[pref]}`}
    >
      {LABEL[pref]}
    </button>
  );
}

const PICK: ThemePreference[] = ["light", "dark", "system"];

export function ThemePicker() {
  const [pref, setPref] = useState<ThemePreference>("system");

  useEffect(() => setPref(getStoredTheme()), []);

  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label="Theme">
      {PICK.map((t) => (
        <button
          key={t}
          type="button"
          className={`rounded-md px-2 py-0.5 text-xs ${pref === t ? "bg-[var(--chip)] font-medium" : "text-[var(--muted)] hover:text-[var(--text)]"}`}
          aria-pressed={pref === t}
          onClick={() => {
            setTheme(t);
            setPref(t);
          }}
        >
          {LABEL[t]}
        </button>
      ))}
    </div>
  );
}
