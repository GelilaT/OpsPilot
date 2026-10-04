"""Organisations, sites and memberships (FR-TEN-02/03, UC-14)."""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from app.api.deps import CurrentPrincipal, Session, require_org_member, require_org_role
from app.core.security import Principal, Role
from app.core.tenancy import services
from app.core.tenancy.models import Membership, Organisation, OrganisationUser

router = APIRouter(tags=["organisation"])


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = "Europe/London"
    currency: str = Field("GBP", min_length=3, max_length=3)
    vat_scheme: str = "uk_standard"
    region: str = "england-and-wales"
    address: str | None = None
    latitude: Decimal | None = Field(None, ge=-90, le=90)
    longitude: Decimal | None = Field(None, ge=-180, le=180)
    covers: int | None = Field(None, ge=1)


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    timezone: str
    currency: str
    vat_scheme: str
    region: str
    address: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    covers: int | None


class OrganisationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    first_site: SiteIn | None = None


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    default_currency: str
    default_timezone: str


class OrganisationCreated(BaseModel):
    organisation: OrganisationOut
    site: SiteOut | None
    refresh_token_required: bool = True


class MeOut(BaseModel):
    user_id: str
    email: str | None
    display_name: str | None
    organisation: OrganisationOut | None
    org_role: Role | None
    sites: list[SiteOut]
    site_roles: dict[uuid.UUID, Role]


class MembershipIn(BaseModel):
    email: EmailStr
    role: Role
    site_id: uuid.UUID | None = None


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str
    site_id: uuid.UUID | None
    role: Role
    display_name: str | None = None
    email: str | None = None


@router.get("/me", response_model=MeOut)
async def me(principal: CurrentPrincipal, session: Session) -> MeOut:
    org = await session.get(Organisation, principal.organisation_id) if principal.organisation_id else None
    ou = await session.get(OrganisationUser, principal.user_id)
    sites = await services.sites_for(session, principal)
    return MeOut(
        user_id=principal.user_id, email=principal.email,
        display_name=ou.display_name if ou else None,
        organisation=OrganisationOut.model_validate(org) if org else None,
        org_role=principal.org_role,
        sites=[SiteOut.model_validate(s) for s in sites],
        site_roles=principal.site_roles,
    )


@router.post("/organisations", response_model=OrganisationCreated, status_code=status.HTTP_201_CREATED)
async def create_organisation(body: OrganisationIn, principal: CurrentPrincipal, session: Session):
    """Create an organisation; the caller becomes its Owner. The client must refresh its JWT afterwards."""
    first = services.SiteInput(**body.first_site.model_dump()) if body.first_site else None
    org, site = await services.create_organisation(session, principal, name=body.name, first_site=first)
    return OrganisationCreated(organisation=OrganisationOut.model_validate(org),
                               site=SiteOut.model_validate(site) if site else None)


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(session: Session, principal: Principal = Depends(require_org_member)):
    return [SiteOut.model_validate(s) for s in await services.sites_for(session, principal)]


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(body: SiteIn, session: Session,
                      principal: Annotated[Principal, Depends(require_org_role(Role.owner))]):
    assert principal.organisation_id
    site = await services.create_site(session, principal.actor, principal.organisation_id,
                                      services.SiteInput(**body.model_dump()))
    return SiteOut.model_validate(site)


@router.get("/memberships", response_model=list[MembershipOut])
async def list_memberships(session: Session,
                           principal: Annotated[Principal, Depends(require_org_role(Role.general_manager))]):
    rows = await session.execute(
        select(Membership, OrganisationUser)
        .join(OrganisationUser, OrganisationUser.user_id == Membership.user_id)
        .where(Membership.organisation_id == principal.organisation_id)
        .order_by(OrganisationUser.display_name)
    )
    return [MembershipOut(id=m.id, user_id=m.user_id, site_id=m.site_id, role=Role(m.role),
                          display_name=u.display_name, email=u.email) for m, u in rows.all()]


@router.post("/memberships", response_model=MembershipOut, status_code=status.HTTP_201_CREATED)
async def add_membership(body: MembershipIn, session: Session,
                         principal: Annotated[Principal, Depends(require_org_role(Role.owner))]):
    assert principal.organisation_id
    m = await services.add_membership(session, principal.actor, principal.organisation_id,
                                      email=body.email, role=body.role, site_id=body.site_id)
    return MembershipOut(id=m.id, user_id=m.user_id, site_id=m.site_id, role=Role(m.role))
