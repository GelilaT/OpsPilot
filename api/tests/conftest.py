"""Test fixtures.

Integration tests run against a real PostgreSQL (TEST_DATABASE_URL, default the local opspilot_test
database). The schema is rebuilt once per session with Alembic. Tokens are signed with an Ed25519
test key and verified through the same JWKS code path as production (FR-AUTH-02).
"""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# The service connects as the least-privilege app role (row-level security applies); migrations as owner.
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://opspilot_app:opspilot_app@localhost:5432/opspilot_test"
)
TEST_OWNER_DB = os.environ.get(
    "TEST_MIGRATION_DATABASE_URL", "postgresql+psycopg://opspilot:opspilot@localhost:5432/opspilot_test"
)
os.environ["DATABASE_URL"] = TEST_DB
os.environ["MIGRATION_DATABASE_URL"] = TEST_OWNER_DB
os.environ.setdefault("CRON_SECRET", "test-cron-secret")
# Tests run offline: recorded/ground-truth AI responses and private storage under var/test-storage.
os.environ["DEFAULT_AI_PROVIDER"] = "fake"
os.environ["STORAGE_LOCAL_DIR"] = str(Path(__file__).resolve().parents[1] / "var" / "test-storage")
os.environ.setdefault("LOG_LEVEL", "WARNING")

ISSUER = "http://test.local"
AUDIENCE = "http://test.local"
API_DIR = Path(__file__).resolve().parents[1]

_private_key = Ed25519PrivateKey.generate()
_jwk = jwt.algorithms.OKPAlgorithm.to_jwk(_private_key.public_key(), as_dict=True)
TEST_JWKS = {"keys": [{**_jwk, "kid": "test-key", "alg": "EdDSA", "use": "sig"}]}


def make_token(
    sub: str | None = None,
    *,
    organisation_id: uuid.UUID | str | None = None,
    sites: dict[Any, str] | None = None,
    org_role: str | None = None,
    email: str | None = None,
    name: str | None = "Test User",
    ttl: int = 900,
    **extra: Any,
) -> str:
    now = int(time.time())
    claims = {
        "sub": sub or f"user_{uuid.uuid4().hex[:12]}",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + ttl,
        "email": email or f"{uuid.uuid4().hex[:8]}@example.test",
        "name": name,
        "organisation_id": str(organisation_id) if organisation_id else None,
        "org_role": org_role,
        "sites": {str(k): v for k, v in (sites or {}).items()},
        **extra,
    }
    return jwt.encode(claims, _private_key, algorithm="EdDSA", headers={"kid": "test-key"})


def _migrate() -> None:
    env = {**os.environ, "DATABASE_URL": TEST_DB, "MIGRATION_DATABASE_URL": TEST_OWNER_DB}
    alembic = [sys.executable, "-m", "alembic"]
    subprocess.run([*alembic, "downgrade", "base"], cwd=API_DIR, env=env, check=True, capture_output=True)
    subprocess.run([*alembic, "upgrade", "head"], cwd=API_DIR, env=env, check=True, capture_output=True)


@pytest.fixture(scope="session")
def migrated_db() -> str:
    _migrate()
    return TEST_DB


@pytest.fixture(scope="session")
async def seeded(migrated_db):
    """Both demo organisations, 63 days of history (8-week baselines; no document rendering)."""
    from app.core.settings import get_settings
    from app.seed.__main__ import run
    from app.simulation.profiles import COPPER_POT, NORTHSIDE

    get_settings.cache_clear()
    return await run([COPPER_POT.slug, NORTHSIDE.slug], 63, documents=False)


@pytest.fixture(scope="session")
def app(migrated_db: str):
    from app.core.security import JWKSCache, TokenVerifier
    from app.core.settings import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    verifier = TokenVerifier(JWKSCache("static", static_jwks=TEST_JWKS), issuer=ISSUER, audience=AUDIENCE)
    return create_app(user_verifier=verifier)


@pytest.fixture
async def client(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as c:
        yield c


def auth(token: str, site_id: Any = None, **headers: str) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}", **headers}
    if site_id:
        h["X-Site-Id"] = str(site_id)
    return h
