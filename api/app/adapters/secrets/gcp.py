"""Secret Manager resolver for `gcp-sm:projects/<p>/secrets/<name>/versions/<v>` references."""

from functools import lru_cache

from app.ports.errors import InvalidCredentialsError


class GcpSecretManagerResolver:
    @lru_cache(maxsize=64)  # noqa: B019 - small, process-lifetime cache of secret values
    def resolve(self, name: str) -> str:
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            return client.access_secret_version(name=name).payload.data.decode()
        except Exception as exc:
            raise InvalidCredentialsError(f"Cannot read secret {name}: {exc}", provider="gcp-sm") from exc
