"""Seed the demo database.

    python -m app.seed --reset           # rebuild the schema, seed both organisations, render documents
    python -m app.seed --days 30         # shorter history (tests)
    python -m app.seed --documents-only  # re-render the demo invoice files only

Uses the owner database role (MIGRATION_DATABASE_URL) with an explicit row-level-security bypass.
"""

import argparse
import asyncio
import logging
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import psycopg

from app.core.settings import get_settings
from app.seed.documents import copper_pot_documents, northside_documents
from app.seed.generator import preview_next_day, seed_bank_holidays, seed_org
from app.simulation.catalogue import Catalogue
from app.simulation.invoice_render import write_documents
from app.simulation.profiles import PROFILES
from app.simulation.scenarios import SEED_DAYS, SEED_END

API_DIR = Path(__file__).resolve().parents[2]
DOCUMENTS = {"copper-pot": copper_pot_documents, "northside-kitchens": northside_documents}


def reset_schema() -> None:
    for step in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run([sys.executable, "-m", "alembic", *step], cwd=API_DIR, check=True)


def _dir(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (API_DIR / p).resolve()


async def run(orgs: list[str], days: int, *, documents: bool = True, seed: bool = True) -> dict:
    settings = get_settings()
    conninfo = settings.owner_database_url.replace("postgresql+psycopg://", "postgresql://")
    summary: dict = {}
    async with await psycopg.AsyncConnection.connect(conninfo) as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.bypass_rls', 'on', true)")
            for slug in orgs:
                profile = PROFILES[slug]
                if seed:
                    counts, worlds = await seed_org(conn, profile, days=days)
                    await seed_bank_holidays(conn, profile.region)
                    summary[slug] = counts
                else:
                    from app.seed.generator import Rows, history_rows

                    cat = Catalogue(profile)
                    worlds = {s.code: history_rows(profile, s, cat, Rows(), SEED_END - timedelta(days=days - 1),
                                                   SEED_END) for s in profile.sites}
                if documents and slug in DOCUMENTS:
                    docs = DOCUMENTS[slug](profile, Catalogue(profile), worlds, SEED_END + timedelta(days=1),
                                           preview_next_day)
                    write_documents(docs, _dir(settings.demo_dir) / "invoices" / slug, _dir(settings.ai_fixtures_dir))
                    summary.setdefault("documents", []).extend(f"{slug}/{d.filename}" for d in docs)
                    summary.setdefault("shas", set()).update(d.sha256 for d in docs)
    if seed:
        summary["history"] = await derive_history(orgs, days)
    if documents and set(orgs) == set(DOCUMENTS):
        # Ground truth only for the documents that exist now (recorded real-AI responses are kept).
        for fixture in _dir(settings.ai_fixtures_dir).glob("*.json"):
            if fixture.stem not in summary.get("shas", set()) and not fixture.name.startswith("recorded-"):
                fixture.unlink()
    return summary


async def derive_history(orgs: list[str], days: int) -> dict:
    """Cost snapshots and the S7 operational record, computed by the domain code as the app role."""
    from app.core.tenancy.context import build_site_context
    from app.core.tenancy.scoping import tenant_unit_of_work
    from app.simulation.history import backfill

    out = {}
    start = SEED_END - timedelta(days=days - 1)
    for slug in orgs:
        profile = PROFILES[slug]
        cat = Catalogue(profile)
        for site in profile.sites:
            async with tenant_unit_of_work(cat.org_id, cat.site_id(site)) as session:
                ctx = await build_site_context(session, cat.org_id, cat.site_id(site), actor="system:seed")
                out[f"{slug}/{site.code}"] = await backfill(ctx, profile, site.code, start, SEED_END)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop and recreate the schema first")
    parser.add_argument("--orgs", default=",".join(PROFILES), help="comma-separated profile slugs")
    parser.add_argument("--days", type=int, default=SEED_DAYS)
    parser.add_argument("--no-documents", action="store_true")
    parser.add_argument("--documents-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.reset and not args.documents_only:
        reset_schema()
    orgs = [o.strip() for o in args.orgs.split(",") if o.strip()]
    summary = asyncio.run(run(orgs, args.days, documents=not args.no_documents, seed=not args.documents_only))
    for slug in orgs:
        if slug in summary:
            total = sum(summary[slug].values())
            print(f"{slug}: {total:,} rows - " + ", ".join(f"{k} {v:,}" for k, v in summary[slug].items()
                                                           if k in ("sales_order", "sales_order_line",
                                                                    "stock_movement", "purchase_order")))
    for doc in summary.get("documents", []):
        print(f"document: demo/invoices/{doc}")
    print("\nDemo sign-ins (password: DEMO_PASSWORD, see app/seed/users.py):")
    for slug in orgs:
        for user in PROFILES[slug].users:
            print(f"  {PROFILES[slug].name:<20} {user.role:<16} {user.email}")


if __name__ == "__main__":
    main()
