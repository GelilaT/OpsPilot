import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { jwt } from "better-auth/plugins";
import { Pool } from "pg";

import { internalAuthHeaders } from "./internal-auth";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const BASE_URL = process.env.BETTER_AUTH_URL ?? "http://localhost:3000";

type TenantClaims = {
  organisation_id: string | null;
  org_role: string | null;
  sites: Record<string, string>;
};

/** Organisation and site-to-role map for the JWT, resolved by the API from memberships (FR-AUTH-02). */
async function tenantClaims(userId: string): Promise<TenantClaims> {
  const res = await fetch(`${API_URL}/internal/auth/claims/${encodeURIComponent(userId)}`, {
    headers: await internalAuthHeaders(),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`claims lookup failed: ${res.status}`);
  return res.json();
}

export const auth = betterAuth({
  baseURL: BASE_URL,
  secret: process.env.BETTER_AUTH_SECRET,
  database: new Pool({ connectionString: process.env.DATABASE_URL, max: 5 }),
  // Better Auth hashes passwords with scrypt (FR-AUTH-01).
  emailAndPassword: { enabled: true, minPasswordLength: 10, autoSignIn: true },
  rateLimit: { enabled: true, window: 60, max: 30 },
  plugins: [
    jwt({
      jwks: { keyPairConfig: { alg: "EdDSA", crv: "Ed25519" } },
      jwt: {
        issuer: BASE_URL,
        audience: BASE_URL,
        expirationTime: "15m",
        definePayload: async ({ user }) => ({
          email: user.email,
          name: user.name,
          ...(await tenantClaims(user.id)),
        }),
      },
    }),
    nextCookies(),
  ],
});
