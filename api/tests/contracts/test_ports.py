"""Port contract suites (FR-INT-04): every adapter of a port must pass the same tests.

Fakes always run. HTTP adapters run against recorded wire behaviour (httpx.MockTransport), which also
checks error translation into typed port errors (FR-INT-05). Live providers run when their credentials
or network access are available:  GEMINI_API_KEY, OPSPILOT_TEST_GCS_BUCKET, SENDGRID_API_KEY,
OPSPILOT_NETWORK_TESTS=1.
"""

import json
import math
import os
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.adapters.accounting.csv_export import CsvAccounting
from app.adapters.ai.fake import FakeAI, hashed_embedding
from app.adapters.calendar.providers import FixtureCalendar, GovUkCalendar
from app.adapters.mail.providers import ConsoleMail, ResendMail, SendGridMail
from app.adapters.pos.csv_import import CsvPos, error_report, parse_sales_csv
from app.adapters.storage.local import LocalStorage
from app.adapters.storage.memory import MemoryStorage
from app.adapters.weather.providers import FixtureWeather, OpenMeteoWeather
from app.core.signing import verify_file_signature
from app.ports.accounting import AccountingPort, ExportInvoice, ExportInvoiceLine
from app.ports.ai import EMBEDDING_DIMENSIONS, AIPort, Classification, DocumentInput, InvoiceExtraction
from app.ports.errors import InvalidCredentialsError, PermanentError, RateLimitedError, TransientError
from app.ports.mail import EmailMessage, MailPort
from app.ports.pos import PosPort
from app.ports.storage import StoragePort
from app.ports.weather import CalendarPort, WeatherPort

NETWORK = os.environ.get("OPSPILOT_NETWORK_TESTS") == "1"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ai"
DEMO = Path(__file__).resolve().parents[3] / "demo" / "invoices"


# ---------------------------------------------------------------------------------------------------
# StoragePort
# ---------------------------------------------------------------------------------------------------
def storage_adapters(tmp_path: Path) -> list[StoragePort]:
    adapters: list[StoragePort] = [MemoryStorage(), LocalStorage(tmp_path, public_base_url="http://api.test",
                                                                  signing_secret="s3cret")]
    if os.environ.get("OPSPILOT_TEST_GCS_BUCKET"):
        from app.adapters.storage.gcs import GCSStorage

        adapters.append(GCSStorage(os.environ["OPSPILOT_TEST_GCS_BUCKET"]))
    return adapters


async def test_storage_contract(tmp_path):
    for adapter in storage_adapters(tmp_path):
        assert isinstance(adapter, StoragePort)
        key = f"contract/{uuid.uuid4().hex}/invoice.pdf"
        assert not await adapter.exists(key)
        assert await adapter.put(b"%PDF-1.7 original", key=key, content_type="application/pdf") == key
        await adapter.put(b"something else", key=key, content_type="application/pdf")  # never overwritten
        assert await adapter.get(key) == b"%PDF-1.7 original"
        assert await adapter.exists(key)
        url = await adapter.signed_url(key, ttl_seconds=600, content_type="application/pdf")
        assert key.split("/")[-1] in url
        with pytest.raises(PermanentError):
            await adapter.get(f"contract/{uuid.uuid4().hex}")


async def test_local_storage_rejects_traversal_and_signs_urls(tmp_path):
    storage = LocalStorage(tmp_path, public_base_url="http://api.test", signing_secret="s3cret")
    with pytest.raises(PermanentError):
        await storage.put(b"x", key="../escape.txt", content_type="text/plain")
    url = httpx.URL(await storage.signed_url("a/b.pdf", ttl_seconds=60, content_type="application/pdf"))
    q = url.params
    assert verify_file_signature("s3cret", "a/b.pdf", int(q["exp"]), q["ct"], q["sig"])
    assert not verify_file_signature("s3cret", "a/other.pdf", int(q["exp"]), q["ct"], q["sig"])
    assert not verify_file_signature("s3cret", "a/b.pdf", 1, q["ct"], q["sig"])  # expired


# ---------------------------------------------------------------------------------------------------
# MailPort
# ---------------------------------------------------------------------------------------------------
def _mail_transport(status: int, body: dict | None = None, headers: dict | None = None, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body or {}, headers=headers or {})

    return httpx.MockTransport(handler)


MESSAGE = EmailMessage(to=("gm@copperpot.example",), subject="PO-CP1-261002-BRM approved", text="Please deliver.",
                       html="<p>Please deliver.</p>", idempotency_key="rec-1:1", tags=("purchase_order",))


async def test_mail_contract_success():
    seen: list[httpx.Request] = []
    adapters: list[MailPort] = [
        ConsoleMail(),
        SendGridMail("SG.key", "OpsPilot <no-reply@opspilot.example>",
                     transport=_mail_transport(202, headers={"x-message-id": "abc"}, seen=seen)),
        ResendMail("re_key", "OpsPilot <no-reply@opspilot.example>",
                   transport=_mail_transport(200, {"id": "re-1"}, seen=seen)),
    ]
    for adapter in adapters:
        assert isinstance(adapter, MailPort)
        result = await adapter.send(MESSAGE)
        assert result.provider == adapter.provider and result.status in ("accepted", "logged")
        assert result.provider_message_id
    sendgrid_body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v3/mail/send" and seen[0].headers["authorization"] == "Bearer SG.key"
    assert sendgrid_body["personalizations"][0]["to"] == [{"email": "gm@copperpot.example"}]
    assert {c["type"] for c in sendgrid_body["content"]} == {"text/plain", "text/html"}
    assert seen[1].headers["idempotency-key"] == "rec-1:1"


@pytest.mark.parametrize(("status", "error"), [(401, InvalidCredentialsError), (403, InvalidCredentialsError),
                                               (429, RateLimitedError), (503, TransientError),
                                               (400, PermanentError)])
async def test_mail_errors_are_typed(status, error):
    for adapter in (SendGridMail("k", "a@b.example", transport=_mail_transport(status)),
                    ResendMail("k", "a@b.example", transport=_mail_transport(status))):
        with pytest.raises(error):
            await adapter.send(MESSAGE)


def test_mail_requires_credentials():
    with pytest.raises(InvalidCredentialsError):
        SendGridMail("", "a@b.example")


async def test_sendgrid_check_validates_scope():
    ok = SendGridMail("k", "a@b.example", transport=_mail_transport(200, {"scopes": ["mail.send"]}))
    assert "mail.send" in await ok.check()
    bad = SendGridMail("k", "a@b.example", transport=_mail_transport(200, {"scopes": ["stats.read"]}))
    with pytest.raises(InvalidCredentialsError):
        await bad.check()


@pytest.mark.skipif(not os.environ.get("SENDGRID_API_KEY"), reason="SENDGRID_API_KEY not set")
async def test_sendgrid_live_check():
    assert await SendGridMail(os.environ["SENDGRID_API_KEY"], "a@b.example").check()


# ---------------------------------------------------------------------------------------------------
# WeatherPort and CalendarPort
# ---------------------------------------------------------------------------------------------------
def _open_meteo_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        start = date.fromisoformat(request.url.params["start_date"])
        end = date.fromisoformat(request.url.params["end_date"])
        days = [date.fromordinal(n).isoformat() for n in range(start.toordinal(), end.toordinal() + 1)]
        return httpx.Response(200, json={"daily": {"time": days, "temperature_2m_max": [18.5] * len(days),
                                                   "temperature_2m_min": [9.1] * len(days),
                                                   "precipitation_sum": [0.4] * len(days)}})

    return httpx.MockTransport(handler)


def weather_adapters() -> list[WeatherPort]:
    adapters: list[WeatherPort] = [FixtureWeather("manchester"), OpenMeteoWeather(transport=_open_meteo_transport())]
    if NETWORK:
        adapters.append(OpenMeteoWeather())
    return adapters


async def test_weather_contract():
    lat, lng = Decimal("53.4808"), Decimal("-2.2426")
    for adapter in weather_adapters():
        assert isinstance(adapter, WeatherPort)
        history = await adapter.history(lat, lng, date(2026, 9, 1), date(2026, 9, 7), "Europe/London")
        assert [d.day for d in history] == [date(2026, 9, n) for n in range(1, 8)]
        assert all(d.temp_max_c >= d.temp_min_c and d.precipitation_mm >= 0 for d in history)


async def test_weather_errors_are_typed():
    for status, error in ((429, RateLimitedError), (502, TransientError), (400, PermanentError)):
        adapter = OpenMeteoWeather(transport=httpx.MockTransport(lambda r, s=status: httpx.Response(s, text="x")))
        with pytest.raises(error):
            await adapter.history(Decimal(1), Decimal(1), date(2026, 9, 1), date(2026, 9, 2), "Europe/London")


def _govuk_transport():
    data = {"england-and-wales": {"events": [{"title": "Summer bank holiday", "date": "2026-08-31"},
                                             {"title": "Christmas Day", "date": "2026-12-25"},
                                             {"title": "New Year's Day", "date": "2027-01-01"}]}}
    return httpx.MockTransport(lambda r: httpx.Response(200, json=data))


async def test_calendar_contract():
    from app.adapters.calendar import providers

    providers._CACHE.clear()
    adapters: list[CalendarPort] = [FixtureCalendar(), GovUkCalendar(transport=_govuk_transport())]
    for adapter in adapters:
        assert isinstance(adapter, CalendarPort)
        days = {h.day: h.title for h in await adapter.holidays("england-and-wales", 2026)}
        assert days[date(2026, 8, 31)] == "Summer bank holiday"
        assert all(d.year == 2026 for d in days)
        assert await adapter.events(Decimal(0), Decimal(0), date(2026, 1, 1), date(2026, 1, 2)) == []
    providers._CACHE.clear()


# ---------------------------------------------------------------------------------------------------
# AIPort
# ---------------------------------------------------------------------------------------------------
def _demo_doc(name: str) -> DocumentInput | None:
    import hashlib

    path = DEMO / "copper-pot" / name
    if not path.exists():
        return None
    data = path.read_bytes()
    mime = "application/pdf" if name.endswith(".pdf") else "image/jpeg"
    return DocumentInput(data, mime, hashlib.sha256(data).hexdigest())


def ai_adapters() -> list[AIPort]:
    adapters: list[AIPort] = [FakeAI(FIXTURES)]
    if os.environ.get("GEMINI_API_KEY"):
        from app.adapters.ai.gemini import GeminiAI

        adapters.append(GeminiAI(os.environ["GEMINI_API_KEY"]))
    return adapters


async def test_ai_contract_on_inv_4471():
    doc = _demo_doc("INV-4471.pdf")
    if doc is None:
        pytest.skip("demo invoices not generated (python -m app.seed)")
    for adapter in ai_adapters():
        assert isinstance(adapter, AIPort)
        cls, info = await adapter.classify(doc)
        assert isinstance(cls, Classification) and cls.document_type == "invoice" and cls.confidence >= 0.6
        assert not cls.multiple_documents and info.provider == adapter.provider
        ex, _ = await adapter.extract(doc)
        assert isinstance(ex, InvoiceExtraction)
        assert ex.invoice_number == "INV-4471" and ex.po_reference == "PO-CP1-261002-ASH"
        assert ex.currency == "GBP" and ex.subtotal == sum(line.line_total for line in ex.lines)
        assert ex.total == ex.subtotal + ex.vat_total
        chicken = next(line for line in ex.lines if "thigh" in line.description.lower())
        assert chicken.quantity == Decimal(12) and chicken.unit_price == Decimal("7.90")
        vector, _ = await adapter.embed("Short delivery of chicken thigh from Ashworth Meats")
        assert len(vector) == EMBEDDING_DIMENSIONS and math.isclose(sum(v * v for v in vector), 1.0, rel_tol=1e-3)


async def test_fake_ai_unknown_document_routes_to_review():
    fake = FakeAI(FIXTURES)
    cls, _ = await fake.classify(DocumentInput(b"random", "application/pdf", "0" * 64))
    assert cls.document_type == "other" and cls.confidence < 0.6
    with pytest.raises(PermanentError):
        await fake.extract(DocumentInput(b"random", "application/pdf", "0" * 64))


def test_hashed_embeddings_are_similar_for_similar_text():
    a = hashed_embedding("short delivery chicken thigh ashworth")
    b = hashed_embedding("chicken thigh short delivery from ashworth meats")
    c = hashed_embedding("fryer oil usage variance")
    cos = lambda x, y: sum(p * q for p, q in zip(x, y, strict=True))  # noqa: E731
    assert cos(a, b) > 0.6 > cos(a, c)


def test_gemini_errors_are_typed():
    from google.genai import errors as genai_errors

    from app.adapters.ai.gemini import translate_error

    def api_error(code: int):
        return genai_errors.APIError(code, {"error": {"message": "x", "status": "X"}})

    assert isinstance(translate_error(api_error(429)), RateLimitedError)
    assert isinstance(translate_error(api_error(403)), InvalidCredentialsError)
    assert isinstance(translate_error(api_error(503)), TransientError)
    assert isinstance(translate_error(api_error(400)), PermanentError)
    assert isinstance(translate_error(httpx.ReadTimeout("t")), TransientError)


# ---------------------------------------------------------------------------------------------------
# PosPort (CSV; the simulator adapter is covered by the integration tests) and AccountingPort
# ---------------------------------------------------------------------------------------------------
CSV = """order_id,business_date,opened_at,closed_at,covers,channel,item_code,item_name,quantity,unit_price,vat_rate,discount,void_quantity
A1,2026-10-02,2026-10-02T12:01:00+01:00,2026-10-02T12:50:00+01:00,2,dine_in,WRAP,Chicken Wrap,2,9.50,20,0,0
A1,2026-10-02,2026-10-02T12:01:00+01:00,2026-10-02T12:50:00+01:00,2,dine_in,COLA,Cola,2,3.00,20,0.60,0
A2,2026-10-02,2026-10-02T13:00:00,2026-10-02T13:20:00+01:00,1,takeaway,WRAP,Chicken Wrap,1,9.50,20,0,0
A3,2026-10-03,2026-10-03T19:00:00+01:00,2026-10-03T19:40:00+01:00,4,dine_in,WRAP,Chicken Wrap,x,9.50,20,0,0
"""


async def test_pos_csv_contract():
    pos = CsvPos(CSV, "GBP")
    assert isinstance(pos, PosPort)
    sales = await pos.fetch_sales(date(2026, 10, 2))
    assert [s.external_order_id for s in sales] == ["A1"]  # A2 has a naive timestamp, A3 a bad quantity
    a1 = sales[0]
    assert a1.covers == 2 and len(a1.lines) == 2
    assert a1.lines[0].unit_price_minor == 950 and a1.lines[0].vat_rate == Decimal("0.2")
    assert a1.lines[1].discount_minor == 60
    assert [e.row for e in pos.errors] == [4, 5]
    assert "row,field,message" in error_report(pos.errors)


def test_pos_csv_requires_columns():
    with pytest.raises(PermanentError):
        parse_sales_csv("order_id,business_date\n1,2026-10-02\n", "GBP")


async def test_accounting_contract():
    adapter = CsvAccounting()
    assert isinstance(adapter, AccountingPort)
    inv = ExportInvoice("id-1", "Ashworth Meats Ltd", "GB284551237", "INV-4471", date(2026, 10, 2), date(2026, 11, 1),
                        "GBP", 58705, 0, 58705,
                        (ExportInvoiceLine("Chicken thigh", Decimal(12), 790, 9480, Decimal(0), "5000"),))
    one = await adapter.export_invoice(inv)
    period = await adapter.export_period([inv, inv], date(2026, 10, 1), date(2026, 10, 31))
    assert one.content_type == "text/csv" and one.records == 1 and period.records == 2
    text = one.content.decode()
    assert text.splitlines()[0].startswith("invoice_id,supplier") and "INV-4471" in text and "94.80" in text
