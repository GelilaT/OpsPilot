"""FastAPI dependencies: unit of work, authentication, role and site scope (FR-AUTH-02..05)."""

import secrets
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import JWKSCache, Principal, Role, TokenVerifier
from app.core.settings import Settings, get_settings
from app.core.tenancy.context import SiteContext, build_site_context
from app.core.tenancy.scoping import bind_system, bind_tenant


async def get_session() -> AsyncIterator[AsyncSession]:
    """Unit of work: one transaction per request, committed when the handler returns."""
    async with get_sessionmaker()() as session, session.begin():
        yield session


def get_user_verifier(request: Request) -> TokenVerifier:
    return request.app.state.user_verifier


def get_internal_verifier(request: Request) -> TokenVerifier | None:
    return getattr(request.app.state, "internal_verifier", None)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token.")
    return authorization[7:].strip()


# Declared so the OpenAPI docs offer an "Authorize" button; verification happens below.
bearer_scheme = HTTPBearer(auto_error=False, description="Better Auth JWT (GET /api/auth/token on the web app)")


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    verifier: TokenVerifier = Depends(get_user_verifier),
) -> Principal:
    if credentials is None:
        raise Unauthorized("Missing bearer token.")
    claims = await verifier.verify(credentials.credentials)
    return Principal.from_claims(claims)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def tenant_session(principal: CurrentPrincipal,
                         session: AsyncSession = Depends(get_session)) -> AsyncSession:
    """The request's transaction bound to the caller's organisation (RLS + repository filters)."""
    await bind_tenant(session, principal.organisation_id)
    return session


async def system_session(session: AsyncSession = Depends(get_session)) -> AsyncSession:
    """Explicit cross-tenant scope; only for trusted service-to-service endpoints."""
    await bind_system(session)
    return session


Session = Annotated[AsyncSession, Depends(tenant_session)]
SystemSession = Annotated[AsyncSession, Depends(system_session)]


def require_org_member(principal: CurrentPrincipal) -> Principal:
    if principal.organisation_id is None:
        raise Forbidden("You are not a member of an organisation yet.", code="no_organisation")
    return principal


def require_org_role(minimum: Role) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """Organisation-wide action (e.g. add a site): needs an org-level membership of at least `minimum`."""

    async def dep(principal: CurrentPrincipal) -> Principal:
        require_org_member(principal)
        if principal.org_role is None or not principal.org_role.at_least(minimum):
            raise Forbidden(f"Requires the {minimum.value} role for the organisation.")
        return principal

    return dep


@dataclass(frozen=True)
class SiteScope:
    """The caller, the site they are acting on and their role there."""

    principal: Principal
    organisation_id: uuid.UUID
    site_id: uuid.UUID
    role: Role

    @property
    def actor(self) -> str:
        return self.principal.actor


def site_scope(minimum: Role = Role.shift_manager) -> Callable[..., Coroutine[Any, Any, SiteScope]]:
    """Resolve X-Site-Id (header) or ?site_id= against the token's site-role map.

    A site the caller is not a member of returns 404 so existence is not disclosed (FR-AUTH-04).
    A member whose role is too low gets 403.
    """

    async def dep(
        principal: CurrentPrincipal,
        x_site_id: Annotated[str | None, Header()] = None,
        site_id: str | None = None,
    ) -> SiteScope:
        raw = x_site_id or site_id
        if not raw:
            raise NotFound("Select a site (X-Site-Id header).", code="site_required")
        try:
            sid = uuid.UUID(raw)
        except ValueError as exc:
            raise NotFound("Site not found.") from exc
        role = principal.role_for(sid)
        if role is None or principal.organisation_id is None:
            raise NotFound("Site not found.")
        if not role.at_least(minimum):
            raise Forbidden(f"Requires {minimum.value} or above at this site.")
        return SiteScope(principal, principal.organisation_id, sid, role)

    return dep


def site_context(minimum: Role = Role.shift_manager) -> Callable[..., Coroutine[Any, Any, SiteContext]]:
    """SiteContext for the selected site: tenant-bound session, effective configuration, adapters."""
    scope_dep = site_scope(minimum)

    async def dep(scope: SiteScope = Depends(scope_dep),
                  session: AsyncSession = Depends(get_session)) -> SiteContext:
        ctx = await build_site_context(session, scope.organisation_id, scope.site_id, actor=scope.actor)
        ctx.role = scope.role  # type: ignore[attr-defined]
        return ctx

    return dep


@dataclass(frozen=True)
class ServiceCaller:
    actor: str


async def require_internal(
    authorization: Annotated[str | None, Header()] = None,
    x_cron_secret: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
    verifier: TokenVerifier | None = Depends(get_internal_verifier),
) -> ServiceCaller:
    """/internal/* accepts Google OIDC tokens of the scheduler/worker service accounts, or
    X-Cron-Secret in fallback mode (FR-AUTH-05)."""
    if x_cron_secret is not None:
        if settings.cron_secret and secrets.compare_digest(x_cron_secret, settings.cron_secret):
            return ServiceCaller("system:cron")
        raise NotFound()
    if authorization and verifier is not None:
        claims = await verifier.verify(_bearer(authorization))
        email = claims.get("email")
        if claims.get("email_verified") and email in settings.internal_service_accounts:
            return ServiceCaller(f"system:{email}")
    raise NotFound()


def build_user_verifier(settings: Settings) -> TokenVerifier:
    return TokenVerifier(
        JWKSCache(settings.jwks_url, settings.jwks_cache_seconds),
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )


def build_internal_verifier(settings: Settings) -> TokenVerifier | None:
    if not settings.internal_oidc_audience:
        return None
    return TokenVerifier(
        JWKSCache(settings.google_jwks_url, 3600),
        issuer=["https://accounts.google.com", "accounts.google.com"],
        audience=settings.internal_oidc_audience,
    )
