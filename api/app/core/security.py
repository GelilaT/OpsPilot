"""JWT verification against a cached JWKS (FR-AUTH-02, FR-AUTH-05) and the authenticated principal.

Better Auth signs a 15-minute JWT whose claims carry the user's organisation and a site-to-role map.
FastAPI verifies signature, exp, iss and aud on every request; the UI is never the enforcement point.
"""

import asyncio
import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWK

from app.core.errors import Unauthorized

ALLOWED_ALGS = ["EdDSA", "RS256", "ES256", "PS256"]


class Role(enum.StrEnum):
    owner = "owner"
    general_manager = "general_manager"
    head_chef = "head_chef"
    shift_manager = "shift_manager"

    @property
    def rank(self) -> int:
        return _RANK[self]

    def at_least(self, other: "Role") -> bool:
        return self.rank >= other.rank


_RANK = {Role.shift_manager: 1, Role.head_chef: 2, Role.general_manager: 3, Role.owner: 4}


@dataclass(frozen=True)
class Principal:
    """Who is calling. `site_roles` comes from the token (memberships resolved at sign-in)."""

    user_id: str
    organisation_id: uuid.UUID | None
    site_roles: dict[uuid.UUID, Role] = field(default_factory=dict)
    org_role: Role | None = None
    email: str | None = None
    name: str | None = None

    @property
    def actor(self) -> str:
        return f"user:{self.user_id}"

    def role_for(self, site_id: uuid.UUID) -> Role | None:
        return self.site_roles.get(site_id)

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> "Principal":
        org = claims.get("organisation_id")
        sites = claims.get("sites") or {}
        try:
            site_roles = {uuid.UUID(k): Role(v) for k, v in sites.items()}
            org_role = Role(claims["org_role"]) if claims.get("org_role") else None
            org_id = uuid.UUID(org) if org else None
        except (ValueError, KeyError) as exc:
            raise Unauthorized("Token claims are malformed.") from exc
        return cls(
            user_id=str(claims["sub"]),
            organisation_id=org_id,
            site_roles=site_roles,
            org_role=org_role,
            email=claims.get("email"),
            name=claims.get("name"),
        )


class JWKSCache:
    """Fetches and caches a JWKS document; refreshes on unknown kid (key rotation)."""

    def __init__(self, url: str, ttl_seconds: int = 600, *, static_jwks: dict | None = None) -> None:
        self.url = url
        self.ttl = ttl_seconds
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()
        if static_jwks is not None:
            self._load(static_jwks)
            self._fetched_at = float("inf")

    def _load(self, jwks: dict) -> None:
        keys: dict[str, PyJWK] = {}
        for jwk in jwks.get("keys", []):
            try:
                keys[jwk.get("kid", "")] = PyJWK(jwk)
            except jwt.PyJWTError:
                continue
        self._keys = keys

    async def _refresh(self) -> None:
        async with self._lock:
            if time.monotonic() - self._fetched_at < 5:  # someone else just refreshed
                return
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(self.url)
                resp.raise_for_status()
                self._load(resp.json())
            self._fetched_at = time.monotonic()

    async def key_for(self, kid: str | None) -> PyJWK:
        stale = time.monotonic() - self._fetched_at > self.ttl
        if stale or (kid or "") not in self._keys:
            try:
                await self._refresh()
            except httpx.HTTPError as exc:
                if not self._keys:
                    raise Unauthorized("Signing keys are unavailable.") from exc
        key = self._keys.get(kid or "") or (next(iter(self._keys.values())) if len(self._keys) == 1 else None)
        if key is None:
            raise Unauthorized("Unknown signing key.")
        return key


class TokenVerifier:
    def __init__(self, jwks: JWKSCache, *, issuer: str | list[str], audience: str) -> None:
        self.jwks = jwks
        self.issuer = issuer
        self.audience = audience

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise Unauthorized("Malformed token.") from exc
        if header.get("alg") not in ALLOWED_ALGS:
            raise Unauthorized("Unsupported token algorithm.")
        key = await self.jwks.key_for(header.get("kid"))
        try:
            return jwt.decode(
                token,
                key=key,
                algorithms=[header["alg"]],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                leeway=10,
            )
        except jwt.ExpiredSignatureError as exc:
            raise Unauthorized("Token expired.", code="token_expired") from exc
        except jwt.PyJWTError as exc:
            raise Unauthorized(f"Invalid token: {exc}.") from exc
