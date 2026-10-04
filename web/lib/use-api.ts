"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { problemMessage } from "@/lib/api/client";
import { useSession } from "@/lib/session";

type Result<T> = { data?: T; error?: unknown };

/** Load data for the current site; refetches when the site or simulator day changes. */
export function useApi<T>(fetcher: () => Promise<Result<T>>, deps: unknown[] = []) {
  const { site, epoch } = useSession();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!site) return;
    const mine = ++seq.current;
    setLoading(true);
    const res = await fetchRef.current();
    if (mine !== seq.current) return; // a newer request superseded this one
    if (res.error) {
      setError(problemMessage(res.error));
      setData(null);
    } else {
      setError(null);
      setData((res.data ?? null) as T | null);
    }
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [site?.id, epoch, ...deps]);

  useEffect(() => {
    load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}
