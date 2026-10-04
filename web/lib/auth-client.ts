"use client";

import { createAuthClient } from "better-auth/react";
import { jwtClient } from "better-auth/client/plugins";

export const authClient = createAuthClient({ plugins: [jwtClient()] });

let cached: { token: string; exp: number } | null = null;

/** Short-lived API token (15 min) from the Better Auth JWT plugin; refreshed 60 s before expiry. */
export async function getApiToken(force = false): Promise<string | null> {
  const now = Date.now() / 1000;
  if (!force && cached && cached.exp - 60 > now) return cached.token;
  const { data, error } = await authClient.token();
  if (error || !data?.token) {
    cached = null;
    return null;
  }
  const payload = JSON.parse(atob(data.token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  cached = { token: data.token, exp: payload.exp };
  return data.token;
}

export function clearApiToken() {
  cached = null;
}
