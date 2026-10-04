"""Tenant isolation (FR-TEN-05).

Two independent layers:

1. Repository layer - every ORM SELECT issued by a tenant-bound session is filtered automatically by
   organisation (and site when the session is bound to one) through `with_loader_criteria`, so a query
   that forgets the filter still only sees its own tenant.
2. PostgreSQL row-level security - each transaction sets `app.org_id`; policies on every tenant table
   compare it with the row's organisation_id. System work (seed, dispatcher, auth claims) opts in to
   `app.bypass_rls` explicitly.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import ForeignKey, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, ORMExecuteState, Session, declared_attr, mapped_column, with_loader_criteria

TENANT_INFO_KEY = "opspilot.tenant"
NIL_ORG = uuid.UUID(int=0)


class OrgScoped:
    """Mixin for any row owned by an organisation (reference data and operational data)."""

    @declared_attr
    def organisation_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("organisation.id", ondelete="CASCADE"), index=True)


class SiteScoped(OrgScoped):
    """Mixin for operational data that belongs to one site."""

    @declared_attr
    def site_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)


@dataclass(frozen=True)
class TenantBinding:
    organisation_id: uuid.UUID
    site_id: uuid.UUID | None = None


async def bind_tenant(session: AsyncSession, organisation_id: uuid.UUID | None,
                      site_id: uuid.UUID | None = None) -> None:
    """Scope this session/transaction to one organisation (and optionally one site).

    A caller without an organisation is bound to the nil organisation and sees nothing.
    """
    org = organisation_id or NIL_ORG
    session.info[TENANT_INFO_KEY] = TenantBinding(org, site_id)
    await session.execute(text("SELECT set_config('app.org_id', :org, true), set_config('app.bypass_rls', 'off', true)"),
                          {"org": str(org)})


async def bind_system(session: AsyncSession) -> None:
    """Explicit cross-tenant scope for trusted system code (seed, dispatcher, auth claims)."""
    session.info.pop(TENANT_INFO_KEY, None)
    await session.execute(text("SELECT set_config('app.bypass_rls', 'on', true), set_config('app.org_id', '', true)"))


def current_binding(session: AsyncSession | Session) -> TenantBinding | None:
    return session.info.get(TENANT_INFO_KEY)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_criteria(state: ORMExecuteState) -> None:
    binding: TenantBinding | None = state.session.info.get(TENANT_INFO_KEY)
    if binding is None or not (state.is_select or state.is_update or state.is_delete):
        return
    if state.execution_options.get("skip_tenant_filter"):
        return
    org = binding.organisation_id
    options = [with_loader_criteria(OrgScoped, lambda cls: cls.organisation_id == org, include_aliases=True)]
    if binding.site_id is not None:
        site = binding.site_id
        options.append(with_loader_criteria(SiteScoped, lambda cls: cls.site_id == site, include_aliases=True))
    state.statement = state.statement.options(*options)


def rls_statements(table: str) -> list[str]:
    """DDL enabling forced row-level security on one tenant table (used by migrations)."""
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS tenant_isolation ON {table}",
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (current_setting('app.bypass_rls', true) = 'on'
                   OR organisation_id = NULLIF(current_setting('app.org_id', true), '')::uuid)
            WITH CHECK (current_setting('app.bypass_rls', true) = 'on'
                   OR organisation_id = NULLIF(current_setting('app.org_id', true), '')::uuid)""",
    ]


@asynccontextmanager
async def tenant_unit_of_work(organisation_id: uuid.UUID, site_id: uuid.UUID | None = None
                              ) -> AsyncIterator[AsyncSession]:
    """One transaction bound to a tenant (jobs and scripts)."""
    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as session, session.begin():
        await bind_tenant(session, organisation_id, site_id)
        yield session


@asynccontextmanager
async def system_unit_of_work() -> AsyncIterator[AsyncSession]:
    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as session, session.begin():
        await bind_system(session)
        yield session
