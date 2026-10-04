# OpsPilot

AI operations and margin management for multi-site restaurants. OpsPilot watches sales, labour, stock and
supplier invoices, spots margin leaks (a supplier price rise, short deliveries, waste, a labour overrun),
investigates the cause, and proposes fixes a manager approves in one click. It then measures whether the fix
worked and remembers the result.

Built against the SRS in [`docs/`](docs) (v2.1). Every requirement id in the code comments (`FR-ACT-05`, etc.)
refers to it.

## What it does

| Flow | What happens |
|---|---|
| **Invoice intake** | Upload a supplier invoice (PDF/photo). Gemini extracts it, rules check it against purchase orders and prices, the manager approves it, and it posts. |
| **Detect** | A nightly pipeline compares each day with the same weekday over the last weeks (median/MAD baselines) and raises anomalies ranked by money at stake. |
| **Investigate** | An agent gathers evidence (invoices, deliveries, menu costs, memory), scores candidate causes and opens an operations case. |
| **Act** | The agent proposes recommendations (switch supplier, change a par level, raise a PO). A role with enough approval limit approves; the agent executes it, e.g. emails a purchase order. |
| **Learn** | After a follow-up window the outcome is measured against a counterfactual and stored as operational memory for the next case. |
| **Brief** | A morning brief every day and a weekly recap every Monday go out by email. A dashboard shows the same numbers, for any past day. |

## Architecture

```
web/  Next.js 15 (React 19, Tailwind v4)      Better Auth sessions + JWT (EdDSA, JWKS)
  |  typed client generated from OpenAPI
api/  FastAPI + async SQLAlchemy               /api/v1/*  (REST, problem+json, idempotency keys)
  |   domain/   business logic, no web or vendor imports (enforced by import-linter)
  |   ports/    interfaces: AI, mail, storage, POS, weather, calendar, accounting
  |   adapters/ Gemini, SendGrid/Resend/console mail, GCS/local storage, simulated POS...
  |   workers/  Procrastinate jobs: pipeline, outcomes, briefs, follow-ups, email, execution
Postgres 16 + pgvector + pg_trgm, row-level security per organisation and site
```

Layering is checked in CI: `api -> workers -> domain -> ports`. Multi-tenancy is enforced twice, in the
repositories and by Postgres row-level security under a non-superuser role.

A demo **simulator** generates a restaurant's trading days (with planted scenarios such as a chicken price
rise or a short delivery) so the full loop can be shown without a real POS. Settings → Simulator advances one day.

## Run it locally

Needs Python 3.12+, Node 22, and Postgres 16 with pgvector (or `docker compose up db`).

```bash
make setup          # venv + pip install, npm install
cp api/.env.example api/.env && cp web/.env.example web/.env.local   # then edit the secrets
make db-roles       # creates the least-privilege opspilot_app role
make migrate
make seed           # two demo organisations, 120 days of history, demo invoices
make api            # http://localhost:8000
make worker         # job runner (needed for the pipeline, email, simulator)
make web            # http://localhost:3000
```

Or all at once: `docker compose up --build` (then `docker compose --profile seed run seed`).

`make seed` prints the demo sign-ins (for example `owner@copperpot.example`, `gm@copperpot.example`). Without
`GEMINI_API_KEY` the AI port replays recorded responses from `api/fixtures`, so the demo runs offline.

### Configuration

See [`api/.env.example`](api/.env.example) and [`web/.env.example`](web/.env.example). The ones people miss:

- `JWT_ISSUER` / `JWT_AUDIENCE` must equal the web app's public URL (`BETTER_AUTH_URL`) exactly.
- `CRON_SECRET` is shared by web and api; it guards `/internal/*`.
- Email: set `DEFAULT_MAIL_PROVIDER=resend` (or `sendgrid`), the key, and `MAIL_FROM`. The default `console`
  provider only logs. Set `notifications.recipients` under Settings → Configuration.
- Scheduling: `POST /internal/dispatch` must be called every 5 minutes with `X-Cron-Secret`
  ([`.github/workflows/dispatch.yml`](.github/workflows/dispatch.yml) does this). Sites running on the simulator are
  advanced by "Simulate next day" instead.

## Try the demo

1. Sign in as the Copper Pot owner. The dashboard shows the latest day; use the date picker to view past days.
2. Settings → Simulator → simulate days until the planted supplier-price scenario fires. The nightly pipeline runs.
3. Open the new case in the Action Centre: evidence, ranked causes, recommendations.
4. Approve a recommendation as the GM. The agent executes it (the purchase-order email is queued).
5. Simulate a week; the outcome is measured and appears on the dashboard.
6. Settings → Emails → send the morning brief and the weekly recap.

## Tests and quality

```bash
make test    # pytest (unit, contract and integration against a real Postgres)
make lint    # ruff, pyright, import-linter, eslint, tsc
make check   # both
make client  # regenerate web/lib/api/openapi.json + schema.d.ts after changing the API
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs all of the above plus an alembic up/down/up
round trip and a check that the generated client is current.

## Repository layout

```
api/app/api/v1      HTTP routers            api/app/simulation   demo restaurant generator
api/app/domain      business logic          api/app/seed         demo data and users
api/app/adapters    vendor integrations     api/migrations       alembic
web/app/(app)       pages                   web/components/ui    shared UI (cards, tabs, date picker)
docs/               SRS and diagrams        openspec/            spec-driven change history
```
