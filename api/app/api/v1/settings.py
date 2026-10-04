"""Configuration by scope (FR-TEN-04, FR-SET-01) and integration connections (FR-INT-03)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Session, require_org_role
from app.core.audit import record_audit, snapshot
from app.core.errors import NotFound, Unprocessable
from app.core.integrations import IntegrationConnection, registry
from app.core.security import Principal, Role
from app.core.tenancy.config import REGISTRY, clear_config_value, resolve_config, set_config_value
from app.core.tenancy.models import Site
from app.ports import IntegrationKind
from app.ports.errors import PortError

router = APIRouter(tags=["settings"])


class ConfigEntry(BaseModel):
    key: str
    value: Any
    source: str  # system | organisation | site
    version: int | None
    description: str


class ConfigPut(BaseModel):
    values: dict[str, Any] = Field(min_length=1)


async def _owner_site(session, principal: Principal, site_id: uuid.UUID | None) -> uuid.UUID | None:
    if site_id is None:
        return None
    if principal.role_for(site_id) is None:
        raise NotFound("Site not found.")
    return site_id


@router.get("/config", response_model=list[ConfigEntry])
async def get_config(session: Session,
                     principal: Annotated[Principal, Depends(require_org_role(Role.owner))],
                     scope: Literal["organisation", "site"] = "organisation",
                     site_id: uuid.UUID | None = None):
    """Effective configuration with the scope each value comes from."""
    site_id = await _owner_site(session, principal, site_id) if scope == "site" else None
    if scope == "site" and site_id is None:
        raise Unprocessable("site_id is required for scope=site.", code="site_required")
    effective = await resolve_config(session, principal.organisation_id, site_id)
    return [ConfigEntry(key=k, value=REGISTRY[k].dump(v.value), source=v.source, version=v.version,
                        description=REGISTRY[k].description) for k, v in sorted(effective.resolved().items())]


@router.put("/config", response_model=list[ConfigEntry])
async def put_config(body: ConfigPut, session: Session,
                     principal: Annotated[Principal, Depends(require_org_role(Role.owner))],
                     scope: Literal["organisation", "site"] = "organisation",
                     site_id: uuid.UUID | None = None):
    """Set values at organisation or site scope; each change is versioned and audited."""
    sid = await _owner_site(session, principal, site_id) if scope == "site" else None
    if scope == "site" and sid is None:
        raise Unprocessable("site_id is required for scope=site.", code="site_required")
    for key, value in body.values.items():
        if value is None:
            await clear_config_value(session, actor=principal.actor, scope=scope, key=key,
                                     organisation_id=principal.organisation_id, site_id=sid)
        else:
            await set_config_value(session, actor=principal.actor, scope=scope, key=key, value=value,
                                   organisation_id=principal.organisation_id, site_id=sid)
    effective = await resolve_config(session, principal.organisation_id, sid)
    return [ConfigEntry(key=k, value=REGISTRY[k].dump(v.value), source=v.source, version=v.version,
                        description=REGISTRY[k].description) for k, v in sorted(effective.resolved().items())
            if k in body.values]


class IntegrationIn(BaseModel):
    kind: IntegrationKind
    provider: str
    site_id: uuid.UUID | None = None
    secret_ref: str | None = Field(None, pattern=r"^(env|gcp-sm):[A-Za-z0-9_/.\-]+$")
    settings: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class IntegrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    provider: str
    site_id: uuid.UUID | None
    secret_ref: str | None
    settings: dict[str, Any]
    enabled: bool
    last_tested_at: datetime | None
    last_test_status: str | None


class EffectiveIntegration(BaseModel):
    kind: str
    site_id: uuid.UUID | None
    provider: str
    source: Literal["system", "organisation", "site"]


class IntegrationsView(BaseModel):
    connections: list[IntegrationOut]
    effective: list[EffectiveIntegration]
    available: dict[str, list[str]]


@router.get("/integrations", response_model=IntegrationsView)
async def list_integrations(session: Session,
                            principal: Annotated[Principal, Depends(require_org_role(Role.owner))]):
    assert principal.organisation_id
    rows = (await session.execute(select(IntegrationConnection).order_by(
        IntegrationConnection.kind, IntegrationConnection.site_id))).scalars().all()
    sites = (await session.execute(select(Site.id))).scalars().all()
    effective = []
    for kind in IntegrationKind:
        for site_id in [None, *sites]:
            try:
                provider, _, _, source = await registry.connection_for(session, kind, principal.organisation_id, site_id)
            except Exception:
                continue
            effective.append(EffectiveIntegration(kind=kind.value, site_id=site_id, provider=provider, source=source))  # type: ignore[arg-type]
    return IntegrationsView(connections=[IntegrationOut.model_validate(r) for r in rows], effective=effective,
                            available={k.value: registry.providers(k) for k in IntegrationKind})


@router.post("/integrations", response_model=IntegrationOut, status_code=status.HTTP_201_CREATED)
async def upsert_integration(body: IntegrationIn, session: Session,
                             principal: Annotated[Principal, Depends(require_org_role(Role.owner))]):
    """Choose the provider for a port at organisation or site scope - a configuration change only."""
    assert principal.organisation_id
    if body.site_id is not None and principal.role_for(body.site_id) is None:
        raise NotFound("Site not found.")
    if not registry.has(body.kind, body.provider):
        raise Unprocessable(f"No {body.kind.value} adapter named {body.provider!r}. "
                            f"Available: {', '.join(registry.providers(body.kind))}.", code="unknown_provider")
    row = (await session.execute(select(IntegrationConnection).where(
        IntegrationConnection.kind == body.kind.value,
        IntegrationConnection.site_id.is_(None) if body.site_id is None else IntegrationConnection.site_id == body.site_id,
    ))).scalar_one_or_none()
    before = snapshot(row) if row else None
    if row is None:
        row = IntegrationConnection(id=uuid.uuid4(), organisation_id=principal.organisation_id, site_id=body.site_id,
                                    kind=body.kind.value)
        session.add(row)
    row.provider, row.secret_ref, row.settings, row.enabled = body.provider, body.secret_ref, body.settings, body.enabled
    row.last_tested_at, row.last_test_status = None, None
    await session.flush()
    record_audit(session, actor=principal.actor, entity_type="integration_connection", entity_id=row.id,
                 action="update" if before else "create", organisation_id=principal.organisation_id,
                 site_id=body.site_id, before=before, after=snapshot(row))
    return IntegrationOut.model_validate(row)


class IntegrationTestResult(BaseModel):
    ok: bool
    provider: str
    detail: str


async def exercise(kind: IntegrationKind, adapter: Any, site: Site | None) -> str:
    """A cheap, non-destructive call through the port proving the connection works."""
    today = datetime.now(UTC).date()
    if hasattr(adapter, "check"):
        return await adapter.check()
    if kind is IntegrationKind.storage:
        key = f"healthchecks/{uuid.uuid4().hex}.txt"
        await adapter.put(b"ok", key=key, content_type="text/plain")
        assert await adapter.get(key) == b"ok"
        return "write and read succeeded"
    if kind is IntegrationKind.weather and site is not None and site.latitude is not None:
        rows = await adapter.forecast(site.latitude, site.longitude, [today], site.timezone)
        return f"forecast returned {len(rows)} day(s)"
    if kind is IntegrationKind.calendar:
        rows = await adapter.holidays(site.region if site else "england-and-wales", today.year)
        return f"{len(rows)} holidays this year"
    if kind is IntegrationKind.pos:
        return f"{len(await adapter.fetch_shifts(today))} shifts available today"
    if kind is IntegrationKind.accounting:
        result = await adapter.export_period([], today, today)
        return f"export produced {result.filename}"
    return "adapter constructed"


@router.post("/integrations/{connection_id}/test", response_model=IntegrationTestResult)
async def test_integration(connection_id: uuid.UUID, session: Session,
                           principal: Annotated[Principal, Depends(require_org_role(Role.owner))]):
    row = await session.get(IntegrationConnection, connection_id)
    if row is None:
        raise NotFound("Integration not found.")
    kind = IntegrationKind(row.kind)
    site = await session.get(Site, row.site_id) if row.site_id else None
    try:
        adapter = registry.build(kind, row.provider, organisation_id=row.organisation_id, site_id=row.site_id,
                                 settings=row.settings or {}, secret_ref=row.secret_ref,
                                 extra_services={"session": session})
        detail, ok = await exercise(kind, adapter, site), True
    except PortError as exc:
        detail, ok = f"{type(exc).__name__}: {exc}", False
    except Exception as exc:
        detail, ok = f"{type(exc).__name__}: {exc}", False
    row.last_tested_at, row.last_test_status = datetime.now(UTC), ("ok: " if ok else "failed: ") + detail[:380]
    record_audit(session, actor=principal.actor, entity_type="integration_connection", entity_id=row.id, action="test",
                 organisation_id=row.organisation_id, site_id=row.site_id, after={"ok": ok, "detail": detail[:380]})
    return IntegrationTestResult(ok=ok, provider=row.provider, detail=detail)

