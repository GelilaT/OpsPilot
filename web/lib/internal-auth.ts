/**
 * Credentials for calling the API's /internal endpoints (FR-AUTH-05).
 * On Cloud Run the web service account's Google OIDC identity token is used; locally the
 * X-Cron-Secret fallback.
 */
export async function internalAuthHeaders(): Promise<Record<string, string>> {
  const audience = process.env.API_OIDC_AUDIENCE;
  if (audience) {
    const res = await fetch(
      `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(audience)}&format=full`,
      { headers: { "Metadata-Flavor": "Google" }, cache: "no-store" },
    );
    if (res.ok) return { Authorization: `Bearer ${await res.text()}` };
  }
  const secret = process.env.CRON_SECRET;
  if (!secret) throw new Error("No internal credentials configured (API_OIDC_AUDIENCE or CRON_SECRET)");
  return { "X-Cron-Secret": secret };
}
