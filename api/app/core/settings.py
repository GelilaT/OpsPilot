"""Service configuration (pydantic-settings). Secrets come from the environment / Secret Manager only."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    service_name: str = "opspilot-api"
    log_level: str = "INFO"

    # PostgreSQL (SQLAlchemy async URL, psycopg 3 driver). The service connects as the least-privilege
    # application role (subject to row-level security); migrations and the seed use the owner role.
    database_url: str = "postgresql+psycopg://opspilot_app:opspilot_app@localhost:5432/opspilot"
    migration_database_url: str = ""
    db_pool_size: int = 5

    # Better Auth JWT verification (FR-AUTH-02)
    jwks_url: str = "http://localhost:3000/api/auth/jwks"
    jwt_issuer: str = "http://localhost:3000"
    jwt_audience: str = "http://localhost:3000"
    jwks_cache_seconds: int = 600

    # /internal/* authentication (FR-AUTH-05)
    cron_secret: str = ""
    internal_oidc_audience: str = ""
    internal_service_accounts: list[str] = Field(default_factory=list)
    google_jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs"

    # CORS for the web app
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Request body limits (SRS 2.3 security requirements)
    max_body_bytes: int = 1 * 1024 * 1024
    max_upload_bytes: int = 20 * 1024 * 1024

    # Gemini rate limits (FR-JOB-07, Free-Tier Budget)
    ai_requests_per_minute: int = 8  # free tier allows 5/min per model; fallbacks have their own quota
    ai_requests_per_day: int = 55  # free tier: 20/day per model x 3 models in the fallback chain

    # Integrations: system-default providers per port (FR-INT-03). Organisations and sites override
    # these with IntegrationConnection rows; secrets are referenced as env:NAME or gcp-sm:<resource>.
    default_ai_provider: str = "gemini"
    default_storage_provider: str = "local"
    default_mail_provider: str = "console"
    default_pos_provider: str = "simulator"
    default_weather_provider: str = "open_meteo"
    default_calendar_provider: str = "govuk"
    default_accounting_provider: str = "csv"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Tried in order when the primary is overloaded or out of quota (free tier: ~20 requests/day per model).
    gemini_fallback_models: list[str] = Field(default_factory=lambda: ["gemini-3.5-flash", "gemini-3.1-flash-lite"])
    sendgrid_api_key: str = ""
    resend_api_key: str = ""
    mail_from: str = "OpsPilot <no-reply@opspilot.example>"

    gcs_bucket: str = ""
    gcp_project: str = ""
    storage_local_dir: str = "var/storage"
    storage_signing_secret: str = "dev-only-storage-signing-secret"
    public_api_url: str = "http://localhost:8000"

    # Run the job worker inside the API process (single-service hosting). Leave off when a worker service exists.
    run_worker: bool = False

    ai_fixtures_dir: str = "fixtures/ai"
    demo_dir: str = "../demo"

    @property
    def owner_database_url(self) -> str:
        return self.migration_database_url or self.database_url

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq URL for Procrastinate's psycopg connector."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
