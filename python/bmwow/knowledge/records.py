"""Read contracts for knowledge consumers; these are not new ontology node types."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bmwow.ontology.models import (
    CapabilityAvailability,
    Context,
    EpistemicStatus,
    Locator,
    Measurement,
    NumericRange,
)

from .types import MappingStatus


class Record(BaseModel):
    # Keep v1's permissive construction; declare the qualifications it must retain.
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class EvidenceReference(Record):
    evidence_id: str
    source_id: str
    record_key: str
    locator: Locator


class QualifiedRecord(Record):
    references: list[EvidenceReference] = Field(default_factory=list)
    context: Context | None = None
    limitations: list[str] = Field(default_factory=list)


class AttributeValue(QualifiedRecord):
    node_id: str
    attribute: str
    value: float | str
    unit: str | None = None
    source_note: str = ""
    as_of: dt.date | None = None
    value_range: NumericRange | None = None
    measurement: Measurement | None = None
    availability: CapabilityAvailability | None = None
    epistemic_status: EpistemicStatus | None = None


class ModelNode(Record):
    node_id: str
    model_code: str | None = None
    name: str
    brand: str
    segment: str
    powertrain: str | None = None
    # v1 registry field means dataset coverage. Portfolio queries use sold_regions.
    regions: list[str] = Field(default_factory=list)
    sold_regions: list[str] = Field(default_factory=list)
    data_coverage: dict[str, list[str]] = Field(default_factory=dict)
    curation_note: str | None = None
    attributes: list[AttributeValue] = Field(default_factory=list)


class FeedbackClassification(Record):
    """Original VFC label projection; legacy wire names refer to Aspect Term/Label."""

    feedback_type: str | None
    vfc_category: str | None
    vfc_issue: str | None
    vfc_combined: str | None
    attribute: str | None
    mapping_status: MappingStatus | None
    locator: Locator

    @property
    def aspect_term(self) -> str | None:
        return self.vfc_category

    @property
    def aspect_label(self) -> str | None:
        return self.vfc_issue


class FeedbackAspect(QualifiedRecord):
    """Imported aspect enrichment, separate from the original VFC classification."""

    aspect_id: str
    locator: Locator
    feedback_type: str | None = None
    aspect_term: str | None = None
    aspect_label: str | None = None
    vfc_category: str
    issue_type: str
    sentiment: Literal["Positive", "Negative", "Neutral"]
    sentiment_score: float | None = Field(default=None, ge=-1, le=1)
    extraction_source: Literal["vfc_label", "llm"]
    quote: str | None = None
    quote_status: Literal["supported", "missing", "mismatch", "not_applicable"]
    imported_at: dt.datetime | None = None


class FeedbackRetrieval(Record):
    """Denominator and selection metadata for one bounded retrieval."""

    total_matching: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    truncated: bool
    selection_policy: str
    limitations: list[str] = Field(default_factory=list)


class FeedbackItem(QualifiedRecord):
    item_id: str
    text: str
    channel: str | None
    market: str | None = None
    date: dt.date | None = None
    rating: float | None = None
    model: str | None = None
    engine_type: str | None = None
    classifications: list[FeedbackClassification] = Field(default_factory=list)
    aspects: list[FeedbackAspect] = Field(default_factory=list)
    retrieval: FeedbackRetrieval | None = None
    imported_at: dt.datetime | None = None


class FeedbackPage(Record):
    items: list[FeedbackItem] = Field(default_factory=list)
    retrieval: FeedbackRetrieval


class DocChunk(QualifiedRecord):
    node_id: str
    doc_title: str
    text: str
    url: str | None = None
    published: dt.date | None = None
    publication_label: str | None = None
    regions: list[str] = Field(default_factory=list)
    kind: Literal["study", "report"] | None = None
    measurement: Measurement | None = None


class FeedbackFilter(Record):
    models: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    since: dt.date | None = None
    limit: int | None = Field(default=None, ge=0)
    engine_types: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class SalesRow(QualifiedRecord):
    model: str
    market: str
    period: str
    units: int
    row_id: str | None = None
    model_codes: list[str] = Field(default_factory=list)
    status: Literal["actual", "source_reported_future", "forecast", "unknown"] = "unknown"
    source_group: str | None = None
    measurement: Measurement | None = None


class StudyScore(QualifiedRecord):
    node_id: str
    model: str
    region: str
    study: str
    question: str | None
    statistic: str
    response_category: str | None
    value: float | None
    measurement: Measurement
