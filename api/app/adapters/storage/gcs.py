"""StoragePort on Google Cloud Storage: private bucket, V4 signed URLs (10 minutes)."""

import asyncio
from datetime import timedelta

from google.api_core import exceptions as gexc

from app.ports.errors import InvalidCredentialsError, PermanentError, PortError, TransientError

PROVIDER = "gcs"


def _translate(exc: Exception) -> PortError:
    if isinstance(exc, (gexc.Unauthorized, gexc.Forbidden)):
        return InvalidCredentialsError(f"GCS access denied: {exc}", provider=PROVIDER)
    if isinstance(exc, gexc.NotFound):
        return PermanentError(f"GCS object or bucket not found: {exc}", provider=PROVIDER)
    if isinstance(exc, (gexc.ServerError, gexc.TooManyRequests, ConnectionError, TimeoutError)):
        return TransientError(f"GCS unavailable: {exc}", provider=PROVIDER)
    return TransientError(f"GCS error: {exc}", provider=PROVIDER)


class GCSStorage:
    provider = PROVIDER

    def __init__(self, bucket: str, *, project: str | None = None) -> None:
        from google.cloud import storage

        if not bucket:
            raise InvalidCredentialsError("GCS bucket is not configured", provider=PROVIDER)
        self._client = storage.Client(project=project or None)
        self._bucket = self._client.bucket(bucket)

    async def put(self, data: bytes, *, key: str, content_type: str) -> str:
        blob = self._bucket.blob(key)

        def upload() -> None:
            try:
                # if_generation_match=0: create only - originals are immutable
                blob.upload_from_string(data, content_type=content_type, if_generation_match=0)
            except gexc.PreconditionFailed:
                return

        try:
            await asyncio.to_thread(upload)
        except Exception as exc:
            raise _translate(exc) from exc
        return key

    async def get(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._bucket.blob(key).download_as_bytes)
        except Exception as exc:
            raise _translate(exc) from exc

    async def exists(self, key: str) -> bool:
        try:
            return await asyncio.to_thread(self._bucket.blob(key).exists)
        except Exception as exc:
            raise _translate(exc) from exc

    async def signed_url(self, key: str, *, ttl_seconds: int = 600, content_type: str | None = None) -> str:
        def sign() -> str:
            import google.auth
            from google.auth.transport import requests as grequests

            credentials, _ = google.auth.default()
            kwargs: dict = {}
            if not hasattr(credentials, "sign_bytes") or getattr(credentials, "token", None) is None:
                # On Cloud Run the default credentials cannot sign locally: use the IAM signBlob API.
                credentials.refresh(grequests.Request())
                kwargs = {"service_account_email": credentials.service_account_email,
                          "access_token": credentials.token}
            return self._bucket.blob(key).generate_signed_url(
                version="v4", expiration=timedelta(seconds=ttl_seconds), method="GET",
                response_type=content_type, **kwargs)

        try:
            return await asyncio.to_thread(sign)
        except Exception as exc:
            raise _translate(exc) from exc
