"""Golden documents against the live Gemini API (opt-in: OPSPILOT_LIVE_AI=1 and GEMINI_API_KEY).

Uses free-tier quota (two calls per invoice), so it does not run by default. Expectations come from the
documents' ground truth (generated invoices) or hand-recorded answers (real samples).
"""

import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.ports.ai import DocumentInput

LIVE = os.environ.get("OPSPILOT_LIVE_AI") == "1" and bool(os.environ.get("GEMINI_API_KEY"))
pytestmark = pytest.mark.skipif(not LIVE, reason="set OPSPILOT_LIVE_AI=1 and GEMINI_API_KEY to call Gemini")
ROOT = Path(__file__).resolve().parents[3] / "demo" / "invoices"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ai"
MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".webp": "image/webp", ".png": "image/png"}
DOCS = [p for p in sorted(ROOT.rglob("*")) if p.suffix in MIME]


def truth(sha: str) -> dict | None:
    for name in (f"recorded-{sha}.json", f"{sha}.json"):
        if (FIXTURES / name).exists():
            return json.loads((FIXTURES / name).read_text())
    return None


@pytest.fixture(scope="module")
def gemini():
    from app.adapters.ai.gemini import GeminiAI
    from app.core.settings import get_settings

    s = get_settings()
    return GeminiAI(os.environ["GEMINI_API_KEY"], model=s.gemini_model, fallback_models=tuple(s.gemini_fallback_models))


async def call(fn, doc):
    """Pace like the pipeline: wait out rate limits and back off on overload."""
    import asyncio

    from app.ports.errors import RateLimitedError, TransientError

    for wait in (2, 8, 32, 60):
        try:
            return await fn(doc)
        except RateLimitedError as exc:
            await asyncio.sleep(min(exc.retry_after, 70))
        except TransientError:
            await asyncio.sleep(wait)
    return await fn(doc)


@pytest.mark.parametrize("path", DOCS, ids=[p.name for p in DOCS])
async def test_golden_document(gemini, path: Path):
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    expected = truth(sha)
    assert expected, f"no ground truth for {path.name}"
    doc = DocumentInput(data, MIME[path.suffix], sha)
    cls, _ = await call(gemini.classify, doc)
    exp_cls = expected["classification"]
    assert cls.document_type == exp_cls["document_type"]
    assert cls.multiple_documents == exp_cls["multiple_documents"]
    if expected["extraction"] is None or exp_cls["multiple_documents"]:
        return
    ex, _ = await call(gemini.extract, doc)
    want = expected["extraction"]
    assert ex.invoice_number == want["invoice_number"] and ex.currency == want["currency"]
    assert ex.total == Decimal(want["total"]) and len(ex.lines) == len(want["lines"])
    for got, exp in zip(ex.lines, want["lines"], strict=True):
        assert got.line_total == Decimal(exp["line_total"]) and got.quantity == Decimal(exp["quantity"])
