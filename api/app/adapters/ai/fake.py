"""In-memory/offline AIPort (FR-INT-04): deterministic answers for tests and offline demos.

Classification and extraction come from recorded fixtures keyed by the document's SHA-256 (ground truth
for documents the simulator generated, or real Gemini responses recorded for golden tests). Unknown
documents are classified as `other` with low confidence so they route to review. Embeddings are a
deterministic hashed bag-of-words, so texts that share words are similar. Narratives are built from the
facts' own template text, so they always pass the Number Guard.
"""

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.ports.ai import (
    EMBEDDING_DIMENSIONS,
    AICallInfo,
    Classification,
    DocumentInput,
    InvoiceExtraction,
)
from app.ports.errors import PermanentError, RateLimitedError

PROVIDER = "fake"


class FakeAI:
    provider = PROVIDER
    model = "fake-1"

    def __init__(self, fixtures_dir: str | Path | None = None, *, fail_with: Exception | None = None) -> None:
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else None
        self.recorded: dict[str, dict[str, Any]] = {}
        self.fail_with = fail_with
        self.calls: list[tuple[str, str]] = []

    def record(self, sha256: str, classification: Classification, extraction: InvoiceExtraction | None) -> None:
        self.recorded[sha256] = {"classification": classification.model_dump(mode="json"),
                                 "extraction": extraction.model_dump(mode="json") if extraction else None}

    def _fixture(self, sha256: str) -> dict[str, Any] | None:
        if sha256 in self.recorded:
            return self.recorded[sha256]
        if self.fixtures_dir is not None:
            for name in (f"recorded-{sha256}.json", f"{sha256}.json"):  # recorded real responses win
                path = self.fixtures_dir / name
                if path.exists():
                    return json.loads(path.read_text())
        return None

    def _info(self) -> AICallInfo:
        return AICallInfo(PROVIDER, self.model, 1, 0, 0)

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    async def classify(self, doc: DocumentInput) -> tuple[Classification, AICallInfo]:
        self.calls.append(("classify", doc.sha256))
        self._maybe_fail()
        fixture = self._fixture(doc.sha256)
        if fixture is None:
            return Classification(document_type="other", confidence=0.3, multiple_documents=False,
                                  reason="Unrecognised document (no recorded response)"), self._info()
        return Classification.model_validate(fixture["classification"]), self._info()

    async def extract(self, doc: DocumentInput) -> tuple[InvoiceExtraction, AICallInfo]:
        self.calls.append(("extract", doc.sha256))
        self._maybe_fail()
        fixture = self._fixture(doc.sha256)
        if fixture is None or fixture.get("extraction") is None:
            raise PermanentError("No recorded extraction for this document", provider=PROVIDER)
        return InvoiceExtraction.model_validate(fixture["extraction"]), self._info()

    async def narrate(self, facts: dict[str, Any], schema: type[BaseModel],
                      instructions: str) -> tuple[BaseModel, AICallInfo]:
        self.calls.append(("narrate", ""))
        self._maybe_fail()
        draft = facts.get("template")
        if draft is None:
            raise PermanentError("Fake narrator needs a 'template' in the facts", provider=PROVIDER)
        return schema.model_validate(draft), self._info()

    async def embed(self, text: str) -> tuple[list[float], AICallInfo]:
        self.calls.append(("embed", text[:40]))
        self._maybe_fail()
        return hashed_embedding(text), self._info()


def hashed_embedding(text: str, dims: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vec = [0.0] * dims
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
        vec[h % dims] += 1.0 if (h >> 32) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class RateLimitedFakeAI(FakeAI):
    """Always 429s - used to test deferral without consuming retries (FR-INV-17)."""

    def __init__(self) -> None:
        super().__init__(fail_with=RateLimitedError("fake 429", retry_after=60, provider=PROVIDER))
