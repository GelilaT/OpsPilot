"""Adapter registration (composition root). Called once per process by app.main and app.workers.app."""

from pathlib import Path

from app.core.integrations import AdapterContext, AdapterRegistry, EnvSecretResolver
from app.core.settings import Settings
from app.ports import IntegrationKind as K

_SINGLETONS: dict[str, object] = {}


def _singleton(name: str, factory):
    if name not in _SINGLETONS:
        _SINGLETONS[name] = factory()
    return _SINGLETONS[name]


def register_all(registry: AdapterRegistry, settings: Settings) -> AdapterRegistry:
    from app.adapters.accounting.csv_export import CsvAccounting
    from app.adapters.ai.fake import FakeAI
    from app.adapters.calendar.providers import FixtureCalendar, GovUkCalendar
    from app.adapters.mail.providers import ConsoleMail, ResendMail, SendGridMail
    from app.adapters.pos.csv_import import CsvPos
    from app.adapters.pos.simulator import SimulatorPos
    from app.adapters.secrets.gcp import GcpSecretManagerResolver
    from app.adapters.storage.local import LocalStorage
    from app.adapters.storage.memory import MemoryStorage
    from app.adapters.weather.providers import FixtureWeather, OpenMeteoWeather

    registry.secrets = EnvSecretResolver({"gcp-sm": GcpSecretManagerResolver()})
    api_dir = Path(__file__).resolve().parents[2]

    def gemini(c: AdapterContext):
        from app.adapters.ai.gemini import GeminiAI

        return GeminiAI(c.secret or settings.gemini_api_key, model=c.settings.get("model", settings.gemini_model),
                        fallback_models=tuple(c.settings.get("fallback_models", settings.gemini_fallback_models)),
                        embedding_model=c.settings.get("embedding_model", "gemini-embedding-001"))

    def gcs(c: AdapterContext):
        from app.adapters.storage.gcs import GCSStorage

        return GCSStorage(c.settings.get("bucket") or settings.gcs_bucket, project=settings.gcp_project or None)

    def local_storage(c: AdapterContext):
        root = Path(c.settings.get("root") or settings.storage_local_dir)
        return LocalStorage(root if root.is_absolute() else api_dir / root, public_base_url=settings.public_api_url,
                            signing_secret=settings.storage_signing_secret)

    def fixtures_dir() -> Path:
        p = Path(settings.ai_fixtures_dir)
        return p if p.is_absolute() else api_dir / p

    registry.register(K.ai, "gemini", gemini)
    registry.register(K.ai, "fake", lambda c: _singleton("ai:fake", lambda: FakeAI(fixtures_dir())))
    registry.register(K.storage, "local", local_storage)
    registry.register(K.storage, "gcs", gcs)
    registry.register(K.storage, "memory", lambda c: _singleton("storage:memory", MemoryStorage))
    registry.register(K.mail, "sendgrid", lambda c: SendGridMail(c.secret or settings.sendgrid_api_key,
                                                                 c.settings.get("sender", settings.mail_from)))
    registry.register(K.mail, "resend", lambda c: ResendMail(c.secret or settings.resend_api_key,
                                                             c.settings.get("sender", settings.mail_from)))
    registry.register(K.mail, "console", lambda c: _singleton("mail:console", ConsoleMail))
    registry.register(K.pos, "simulator", lambda c: SimulatorPos(
        profile=c.settings["profile"], site_code=c.settings["site_code"], organisation_id=c.organisation_id,
        site_id=c.site_id, session=c.services.get("session")))  # type: ignore[arg-type]
    registry.register(K.pos, "csv", lambda c: CsvPos(c.settings.get("csv_text", ""), c.settings.get("currency", "GBP")))
    registry.register(K.weather, "open_meteo", lambda c: OpenMeteoWeather())
    registry.register(K.weather, "fixture", lambda c: FixtureWeather(c.settings.get("city", "")))
    registry.register(K.calendar, "govuk", lambda c: GovUkCalendar())
    registry.register(K.calendar, "fixture", lambda c: FixtureCalendar())
    registry.register(K.accounting, "csv", lambda c: CsvAccounting())

    ai_default = settings.default_ai_provider
    if ai_default == "gemini" and not settings.gemini_api_key:
        ai_default = "fake"  # degraded mode: no key configured -> recorded responses only
    registry.set_default(K.ai, ai_default)
    registry.set_default(K.storage, settings.default_storage_provider)
    registry.set_default(K.mail, settings.default_mail_provider)
    registry.set_default(K.weather, settings.default_weather_provider)
    registry.set_default(K.calendar, settings.default_calendar_provider)
    registry.set_default(K.accounting, settings.default_accounting_provider)
    return registry
