"""AIPort and the AI contracts of SRS Appendix A (normative for FR-INV-04, FR-INV-05, FR-RCA-07).

Every provider must return outputs that validate against these schemas before use (FR-INT-06).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["invoice", "credit_note", "statement", "delivery_note", "purchase_order", "receipt", "other"]


@dataclass(frozen=True)
class DocumentInput:
    """A stored document passed to the model as data parts (never as instructions)."""

    content: bytes
    mime: str
    sha256: str
    pages: int = 1


class Classification(BaseModel):
    """A.1 Classification response schema."""

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    confidence: float = Field(ge=0, le=1)
    multiple_documents: bool
    reason: str = Field(max_length=200)


class ExtractedSupplier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    vat_number: str | None = None
    address: str | None = None


class ExtractedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    supplier_sku: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    pack_size: str | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    vat_rate: Decimal | None = None


class InvoiceExtraction(BaseModel):
    """A.2 Extraction response schema (CanonicalInvoiceExtraction). Fields are optional and never guessed."""

    model_config = ConfigDict(extra="forbid")

    supplier: ExtractedSupplier = Field(default_factory=ExtractedSupplier)
    invoice_number: str | None = None
    invoice_date: str | None = None
    delivery_date: str | None = None
    due_date: str | None = None
    po_reference: str | None = None
    currency: str | None = None
    lines: list[ExtractedLine] = Field(default_factory=list)
    subtotal: Decimal | None = None
    vat_total: Decimal | None = None
    total: Decimal | None = None
    field_confidence: dict[str, float] = Field(default_factory=dict)


class NarrativeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    text: str


class NarrativeCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cause_code: str
    confidence_node_id: str
    text: str


class InvestigationNarrative(BaseModel):
    """A.3 Investigation narrative schema; every number must appear in the referenced node facts."""

    model_config = ConfigDict(extra="forbid")

    finding: str
    evidence: list[NarrativeEvidence]
    causes: list[NarrativeCause]
    next_action: str


@dataclass(frozen=True)
class AICallInfo:
    """Observability for the AI call log (SRS 2.4): purpose, model, latency, tokens."""

    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class AIPort(Protocol):
    provider: str
    model: str

    async def classify(self, doc: DocumentInput) -> tuple[Classification, AICallInfo]: ...

    async def extract(self, doc: DocumentInput) -> tuple[InvoiceExtraction, AICallInfo]: ...

    async def narrate(self, facts: dict[str, Any], schema: type[BaseModel],
                      instructions: str) -> tuple[BaseModel, AICallInfo]: ...

    async def embed(self, text: str) -> tuple[list[float], AICallInfo]: ...


EMBEDDING_DIMENSIONS = 768
