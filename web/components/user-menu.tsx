"use client";

import { useEffect, useRef, useState } from "react";

import { ThemePicker } from "@/components/theme-toggle";
import { label } from "@/lib/format";

export function UserMenu({
  name,
  role,
  onSignOut,
}: {
  name: string | null | undefined;
  role: string | null | undefined;
  onSignOut: () => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const display = name?.trim() || "Account";

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        className="btn-secondary btn-sm flex max-w-[10rem] items-center gap-1 truncate"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="truncate">{display}</span>
        <span aria-hidden className="shrink-0 text-[var(--muted)]">
          ▾
        </span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-56 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 shadow-md"
        >
          <div className="border-b border-[var(--border)] pb-2">
            <p className="truncate text-sm font-medium">{display}</p>
            {role && <p className="text-xs text-[var(--muted)]">{label(role)}</p>}
          </div>
          <div className="border-b border-[var(--border)] py-2">
            <p className="mb-1.5 text-xs text-[var(--muted)]">Theme</p>
            <ThemePicker />
          </div>
          <button
            type="button"
            role="menuitem"
            className="mt-2 w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-[var(--chip)]"
            onClick={() => {
              setOpen(false);
              onSignOut();
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
