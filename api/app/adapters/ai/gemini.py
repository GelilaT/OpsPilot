"""AIPort adapter for Google Gemini (structured output, document understanding, embeddings)."""

import json
import re
import time
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.adapters.ai import prompts
from app.ports.ai import (
    EMBEDDING_DIMENSIONS,
    AICallInfo,
    Classification,
    DocumentInput,
    InvoiceExtraction,
)
from app.ports.errors import (
    InvalidCredentialsError,
    PermanentError,
    PortError,
    RateLimitedError,
    TransientError,
)

PROVIDER = "gemini"


def translate_error(exc: Exception) -> PortError:
    """Vendor failures -> typed port errors (FR-INT-05)."""
    if isinstance(exc, genai_errors.APIError):
        code = exc.code or 0
        if code == 429:
            match = re.search(r"retry in ([\d.]+)s", exc.message or "")
            wait = float(match.group(1)) if match else 60.0
            return RateLimitedError(f"Gemini rate limit: {(exc.message or '')[:200]}", retry_after=max(1.0, wait),
                                    provider=PROVIDER)
        if code in (401, 403):
            return InvalidCredentialsError(f"Gemini rejected the API key: {exc.message}", provider=PROVIDER)
        if code >= 500 or code == 408:
            return TransientError(f"Gemini unavailable ({code}): {exc.message}", provider=PROVIDER)
        return PermanentError(f"Gemini rejected the request ({code}): {exc.message}", provider=PROVIDER)
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, ConnectionError)):
        return TransientError(f"Gemini connection problem: {exc}", provider=PROVIDER)
    return TransientError(f"Unexpected Gemini error: {exc}", provider=PROVIDER)


class GeminiAI:
    provider = PROVIDER

    def __init__(self, api_key: str, *, model: str = "gemini-3.8-flash", fallback_models: tuple[str, ...] = (),
                 embedding_model: str = "gemini-embedding-001", timeout_s: float = 90) -> None:
        if not api_key:
            raise InvalidCredentialsError("GEMINI_API_KEY is not configured", provider=PROVIDER)
        self.model = model
        self.fallback_models = tuple(m for m in fallback_models if m != model)
        self.embedding_model = embedding_model
        self._client = genai.Client(api_key=api_key,
                                    http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))

    async def check(self) -> str:
        """Non-billable connection check: read the configured model's metadata."""
        try:
            model = await self._client.aio.models.get(model=self.model)
        except Exception as exc:
            raise translate_error(exc) from exc
        return f"model {model.name} available"

    async def _generate(self, parts: list[Any], schema: dict, system: str) -> tuple[dict, AICallInfo]:
        """Primary model first; when it is overloaded (5xx) or out of quota (429 - quotas are per model),
        try the configured fallback models in order. The last error is raised if all fail."""
        last: PortError | None = None
        for model in (self.model, *self.fallback_models):
            try:
                return await self._generate_with(model, parts, schema, system)
            except (TransientError, RateLimitedError) as exc:
                last = exc
        assert last is not None
        raise last

    async def _generate_with(self, model: str, parts: list[Any], schema: dict, system: str) -> tuple[dict, AICallInfo]:
        started = time.perf_counter()
        try:
            resp = await self._client.aio.models.generate_content(
                model=model,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except Exception as exc:
            raise translate_error(exc) from exc
        usage = resp.usage_metadata
        info = AICallInfo(PROVIDER, model, int((time.perf_counter() - started) * 1000),
                          getattr(usage, "prompt_token_count", None), getattr(usage, "candidates_token_count", None))
        if not resp.text:
            raise PermanentError("Gemini returned no content (possibly blocked)", provider=PROVIDER)
        try:
            return json.loads(resp.text), info
        except json.JSONDecodeError as exc:
            raise PermanentError(f"Gemini returned invalid JSON: {exc}", provider=PROVIDER) from exc

    @staticmethod
    def _doc_part(doc: DocumentInput) -> types.Part:
        return types.Part.from_bytes(data=doc.content, mime_type=doc.mime)

    async def classify(self, doc: DocumentInput) -> tuple[Classification, AICallInfo]:
        data, info = await self._generate([self._doc_part(doc), prompts.CLASSIFY], prompts.CLASSIFICATION_SCHEMA,
                                          prompts.SYSTEM_DOCUMENT)
        data["reason"] = str(data.get("reason", ""))[:200]
        data["confidence"] = min(1.0, max(0.0, float(data.get("confidence", 0))))
        try:
            return Classification.model_validate(data), info
        except ValidationError as exc:
            raise PermanentError(f"Classification failed schema validation: {exc}", provider=PROVIDER) from exc

    async def extract(self, doc: DocumentInput) -> tuple[InvoiceExtraction, AICallInfo]:
        data, info = await self._generate([self._doc_part(doc), prompts.EXTRACT], prompts.EXTRACTION_SCHEMA,
                                          prompts.SYSTEM_DOCUMENT)
        data["field_confidence"] = {k: v for k, v in (data.get("field_confidence") or {}).items() if v is not None}
        try:
            return InvoiceExtraction.model_validate(data), info
        except ValidationError as exc:
            raise PermanentError(f"Extraction failed schema validation: {exc}", provider=PROVIDER) from exc

    async def narrate(self, facts: dict[str, Any], schema: type[BaseModel],
                      instructions: str) -> tuple[BaseModel, AICallInfo]:
        payload = json.dumps(facts, default=str)
        data, info = await self._generate([f"{instructions}\n\nFACTS (JSON):\n{payload}"],
                                          _gemini_schema(schema.model_json_schema()), prompts.NARRATE)
        try:
            return schema.model_validate(data), info
        except ValidationError as exc:
            raise PermanentError(f"Narrative failed schema validation: {exc}", provider=PROVIDER) from exc

    async def embed(self, text: str) -> tuple[list[float], AICallInfo]:
        started = time.perf_counter()
        try:
            resp = await self._client.aio.models.embed_content(
                model=self.embedding_model, contents=text,
                config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS,
                                                task_type="SEMANTIC_SIMILARITY"),
            )
        except Exception as exc:
            raise translate_error(exc) from exc
        values = list(resp.embeddings[0].values or []) if resp.embeddings else []
        if len(values) != EMBEDDING_DIMENSIONS:
            raise PermanentError(f"Unexpected embedding size {len(values)}", provider=PROVIDER)
        return values, AICallInfo(PROVIDER, self.embedding_model, int((time.perf_counter() - started) * 1000))


def _gemini_schema(schema: dict) -> dict:
    """Inline $defs and drop keywords Gemini's response_schema does not accept."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items()
                    if k not in ("$defs", "title", "additionalProperties", "default")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)
