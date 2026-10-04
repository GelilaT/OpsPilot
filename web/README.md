# OpsPilot web

Next.js 15 app (App Router, Tailwind v4). See the [root README](../README.md) for the whole system.

```bash
cp .env.example .env.local
npm install
npm run dev          # http://localhost:3000
npm run lint && npm run typecheck
npm run api:types    # regenerate lib/api/schema.d.ts from lib/api/openapi.json
```

- `app/(app)/` authenticated pages; `app/sign-in` and `app/api/auth` are Better Auth.
- `lib/api/client.ts` is the typed API client; `lib/use-api.ts` the data hook.
- `components/ui.tsx` holds the shared UI pieces.
