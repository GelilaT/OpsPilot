"""Demo users for the seeded organisations, created directly in Better Auth's tables.

Passwords are hashed exactly like Better Auth (scrypt N=16384, r=16, p=1, 64-byte key, hex salt) so the
users can sign in through the web app. The demo password is a development value for seeded demo data
only; override it with DEMO_PASSWORD.
"""

import hashlib
import os
import secrets
import unicodedata

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "OpsPilot-demo-2026")


def better_auth_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(unicodedata.normalize("NFKC", password).encode(), salt=salt.encode(), n=16384, r=16, p=1,
                         dklen=64, maxmem=128 * 16384 * 16 * 2)
    return f"{salt}:{key.hex()}"


def verify_better_auth_hash(stored: str, password: str) -> bool:
    salt, key = stored.split(":")
    derived = hashlib.scrypt(unicodedata.normalize("NFKC", password).encode(), salt=salt.encode(), n=16384, r=16,
                             p=1, dklen=64, maxmem=128 * 16384 * 16 * 2)
    return secrets.compare_digest(derived.hex(), key)
