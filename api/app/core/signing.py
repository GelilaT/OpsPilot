"""HMAC-signed, expiring URLs for files served by the API itself (local storage adapter)."""

import base64
import hashlib
import hmac
import time
from urllib.parse import quote, urlencode


def _sig(secret: str, key: str, exp: int, content_type: str) -> str:
    msg = f"{key}\n{exp}\n{content_type}".encode()
    return base64.urlsafe_b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode().rstrip("=")


def sign_file_url(base_url: str, secret: str, key: str, ttl_seconds: int, content_type: str) -> str:
    exp = int(time.time()) + ttl_seconds
    query = urlencode({"exp": exp, "ct": content_type, "sig": _sig(secret, key, exp, content_type)})
    return f"{base_url.rstrip('/')}/files/{quote(key)}?{query}"


def verify_file_signature(secret: str, key: str, exp: int, content_type: str, sig: str) -> bool:
    if exp < time.time():
        return False
    return hmac.compare_digest(_sig(secret, key, exp, content_type), sig)
