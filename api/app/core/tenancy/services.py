"""Onboarding use cases: organisations, sites and memberships (FR-TEN-02, FR-TEN-03, UC-14).

Adding an organisation or a site is data only - no code change, migration or redeploy.
"""

import re
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit, snapshot
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.money import is_iso_currency
from app.core.security import Principal, Role
from app.core.tenancy.models import Membership, Organisation, OrganisationUser, Site
from app.core.tenancy.scoping import bind_tenant


@dataclass
class SiteInput:
    name: str
    timezone: str
    currency: str
    vat_scheme: str = "uk_standard"
    region: str = "england-and-wales"
    address: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    covers: int | None = None


def _validate_site(data: SiteInput) -> None:
    try:
        ZoneInfo(data.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise Unprocessable(f"Unknown timezone {data.timezone!r}.", code="invalid_timezone") from exc
    if not is_iso_currency(data.currency):
        raise Unprocessable(f"Unsupported currency {data.currency!r}.", code="invalid_currency")


def display_name(name: str | None, email: str) -> str:
    """First name + last initial only (GDPR minimisation, SRS 1.3)."""
    parts = (name or email.split("@")[0]).split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return parts[0] if parts else email


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"


async def create_organisation(
    session: AsyncSession, principal: Principal, *, name: str, first_site: SiteInput | None = None
) -> tuple[Organisation, Site | None]:
    if principal.organisation_id is not None:
        raise Conflict("You already belong to an organisation.", code="already_member")
    if first_site is not None:
        _validate_site(first_site)

    org_id = uuid.uuid4()
    await bind_tenant(session, org_id)  # the new organisation is the only tenant this transaction touches
    slug = f"{_slugify(name)}-{secrets.token_hex(3)}"
    org = Organisation(id=org_id, name=name, slug=slug,
                       default_currency=first_site.currency if first_site else "GBP",
                       default_timezone=first_site.timezone if first_site else "Europe/London")
    session.add(org)
    try:
        async with session.begin_nested():
            session.add(OrganisationUser(user_id=principal.user_id, organisation_id=org.id,
                                         email=principal.email or "",
                                         display_name=display_name(principal.name, principal.email or "")))
            await session.flush()
    except IntegrityError as exc:  # the user already belongs to an organisation (hidden from us by RLS)
        raise Conflict("You already belong to an organisation.", code="already_member") from exc
    owner = Membership(organisation_id=org.id, user_id=principal.user_id, site_id=None, role=Role.owner.value)
    session.add(owner)
    record_audit(session, actor=principal.actor, entity_type="organisation", entity_id=org.id, action="create",
                 organisation_id=org.id, after=snapshot(org))
    record_audit(session, actor=principal.actor, entity_type="membership", entity_id=owner.id, action="create",
                 organisation_id=org.id, after=snapshot(owner))
    site = None
    if first_site is not None:
        site = await create_site(session, principal.actor, org.id, first_site)
    return org, site


async def create_site(session: AsyncSession, actor: str, organisation_id: uuid.UUID, data: SiteInput) -> Site:
    _validate_site(data)
    site = Site(id=uuid.uuid4(), organisation_id=organisation_id, **data.__dict__)
    session.add(site)
    await session.flush()
    record_audit(session, actor=actor, entity_type="site", entity_id=site.id, action="create",
                 organisation_id=organisation_id, site_id=site.id, after=snapshot(site))
    return site


async def sites_for(session: AsyncSession, principal: Principal) -> list[Site]:
    """Only sites the caller is a member of (FR-TEN-03)."""
    if principal.organisation_id is None or not principal.site_roles:
        return []
    rows = await session.execute(
        select(Site).where(Site.organisation_id == principal.organisation_id,
                           Site.id.in_(list(principal.site_roles))).order_by(Site.name)
    )
    return list(rows.scalars())


async def find_auth_user(session: AsyncSession, email: str) -> tuple[str, str | None] | None:
    """Look up a Better Auth user by email (the web app owns the "user" table)."""
    try:
        async with session.begin_nested():
            row = (await session.execute(text('SELECT id, name FROM "user" WHERE lower(email) = lower(:e)'),
                                         {"e": email})).first()
    except ProgrammingError:
        return None
    return (row[0], row[1]) if row else None


async def add_membership(
    session: AsyncSession, actor: str, organisation_id: uuid.UUID, *, email: str, role: Role,
    site_id: uuid.UUID | None,
) -> Membership:
    if site_id is not None:
        site = await session.get(Site, site_id)
        if site is None or site.organisation_id != organisation_id:
            raise NotFound("Site not found.")
    found = await find_auth_user(session, email)
    if found is None:
        raise NotFound("No user with that email has signed up yet; ask them to create an account first.",
                       code="user_not_found")
    user_id, name = found
    org_user = await session.get(OrganisationUser, user_id)
    if org_user is None:
        try:
            async with session.begin_nested():
                session.add(OrganisationUser(user_id=user_id, organisation_id=organisation_id, email=email,
                                             display_name=display_name(name, email)))
                await session.flush()
        except IntegrityError as exc:  # a user of another organisation (invisible here by design)
            raise Conflict("That user belongs to another organisation.", code="user_in_other_org") from exc

    existing = (await session.execute(select(Membership).where(
        Membership.user_id == user_id,
        Membership.site_id.is_(None) if site_id is None else Membership.site_id == site_id,
    ))).scalar_one_or_none()
    if existing is not None:
        before = snapshot(existing)
        existing.role = role.value
        record_audit(session, actor=actor, entity_type="membership", entity_id=existing.id, action="update",
                     organisation_id=organisation_id, site_id=site_id, before=before, after=snapshot(existing))
        return existing
    m = Membership(id=uuid.uuid4(), organisation_id=organisation_id, user_id=user_id, site_id=site_id,
                   role=role.value)
    session.add(m)
    await session.flush()
    record_audit(session, actor=actor, entity_type="membership", entity_id=m.id, action="create",
                 organisation_id=organisation_id, site_id=site_id, after=snapshot(m))
    return m


async def claims_for_user(session: AsyncSession, user_id: str) -> dict:
    """JWT claims for Better Auth: organisation and the site -> role map (FR-AUTH-02, FR-TEN-03).

    An organisation-wide membership (no site) applies to every site; a site-specific membership
    overrides it for that site.
    """
    org_user = await session.get(OrganisationUser, user_id)
    if org_user is None:
        return {"organisation_id": None, "org_role": None, "sites": {}}
    memberships = list((await session.execute(
        select(Membership).where(Membership.user_id == user_id,
                                 Membership.organisation_id == org_user.organisation_id)
    )).scalars())
    org_role = next((m.role for m in memberships if m.site_id is None), None)
    sites: dict[str, str] = {}
    if org_role:
        all_sites = (await session.execute(
            select(Site.id).where(Site.organisation_id == org_user.organisation_id))).scalars()
        sites = {str(s): org_role for s in all_sites}
    for m in memberships:
        if m.site_id is not None:
            sites[str(m.site_id)] = m.role
    return {"organisation_id": str(org_user.organisation_id), "org_role": org_role, "sites": sites}


async def actor_names(session: AsyncSession, actors: Iterable[str | None]) -> dict[str, str]:
    """Display names for `user:<id>` actors (first name + last initial); system actors map to themselves."""
    ids = {a.removeprefix("user:") for a in actors if a and a.startswith("user:")}
    if not ids:
        return {}
    rows = await session.execute(select(OrganisationUser.user_id, OrganisationUser.display_name).where(
        OrganisationUser.user_id.in_(ids)))
    return {f"user:{u}": n for u, n in rows.all()}


def actor_label(names: dict[str, str], actor: str | None) -> str | None:
    if actor is None:
        return None
    if actor in names:
        return names[actor]
    return {"agent": "OpsPilot agent"}.get(actor, actor.replace("system:", "OpsPilot ").replace("-", " "))
