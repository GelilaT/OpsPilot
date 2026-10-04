"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, problemMessage, setCurrentSite, type Schemas } from "@/lib/api/client";

type Me = Schemas["MeOut"];
type Site = Schemas["SiteOut"];

type Session = {
  me: Me | null;
  error: string | null;
  site: Site | null;
  role: string | null;
  setSite: (id: string) => void;
  reload: () => Promise<void>;
  /** Bumped when the simulator advances so pages refetch. */
  epoch: number;
  bump: () => void;
};

const Ctx = createContext<Session | null>(null);
const SITE_KEY = "opspilot.site";

const RANK: Record<string, number> = { shift_manager: 1, head_chef: 2, general_manager: 3, owner: 4 };

export function atLeast(role: string | null, minimum: string): boolean {
  return (RANK[role ?? ""] ?? 0) >= (RANK[minimum] ?? 99);
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [siteId, setSiteId] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);

  const reload = useCallback(async () => {
    const { data, error } = await api.GET("/api/v1/me");
    if (error) {
      setError(problemMessage(error));
      return;
    }
    setMe(data);
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(SITE_KEY);
    } catch {
      stored = null;
    }
    const id = data.sites.find((s) => s.id === stored)?.id ?? data.sites[0]?.id ?? null;
    setCurrentSite(id);
    setSiteId(id);
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const value = useMemo<Session>(() => {
    const site = me?.sites.find((s) => s.id === siteId) ?? null;
    const role = site ? (me?.site_roles[site.id] as string | undefined) ?? (me?.org_role as string | null) : null;
    return {
      me,
      error,
      site,
      role: role ?? null,
      epoch,
      bump: () => setEpoch((e) => e + 1),
      reload,
      setSite: (id: string) => {
        try {
          localStorage.setItem(SITE_KEY, id);
        } catch {
          /* private mode: the choice lasts for this tab */
        }
        setCurrentSite(id);
        setSiteId(id);
        setEpoch((e) => e + 1);
      },
    };
  }, [me, error, siteId, epoch, reload]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}
