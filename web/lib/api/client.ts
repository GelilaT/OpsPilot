"use client";

import createClient, { type Middleware } from "openapi-fetch";

import { getApiToken } from "@/lib/auth-client";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

/** RFC 7807 problem returned by the API (FR-API-02). */
export type Problem = {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  request_id: string | null;
  errors?: { field: string; message: string }[];
};

let currentSiteId: string | null = null;

export function setCurrentSite(siteId: string | null) {
  currentSiteId = siteId;
}

export function getCurrentSite() {
  return currentSiteId;
}

const auth: Middleware = {
  async onRequest({ request }) {
    const token = await getApiToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    if (currentSiteId && !request.headers.has("X-Site-Id")) request.headers.set("X-Site-Id", currentSiteId);
    // Financial mutations are idempotent (FR-API-03): every POST/PATCH carries a key.
    if ((request.method === "POST" || request.method === "PATCH") && !request.headers.has("Idempotency-Key")) {
      request.headers.set("Idempotency-Key", crypto.randomUUID());
    }
    return request;
  },
};

/** Typed client generated from the API's OpenAPI 3.1 schema (FR-API-01). */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const api = createClient<paths>({ baseUrl: API_BASE });
api.use(auth);

/** Multipart upload (openapi-fetch does not build FormData bodies). */
export async function uploadInvoice(file: File): Promise<{ data?: Schemas["DocumentDetail"]; error?: Problem }> {
  const token = await getApiToken();
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/v1/invoices`, {
    method: "POST",
    body: form,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(currentSiteId ? { "X-Site-Id": currentSiteId } : {}),
      "Idempotency-Key": crypto.randomUUID(),
    },
  });
  const body = await res.json();
  return res.ok ? { data: body } : { error: body };
}

export function problemMessage(error: unknown): string {
  const p = error as Partial<Problem> | undefined;
  if (p?.errors?.length) return p.errors.map((e) => `${e.field}: ${e.message}`).join("; ");
  return p?.detail ?? "Something went wrong.";
}
