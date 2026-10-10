"""Evidence schemas for the situation analysis hand-off (AGENT_SPEC §3).

PROPOSED by the `src/agent/` builder. If a teammate owns `src/models/`, move or merge these here;
`src/agent/` only imports them from this module. Field names are fixed; new fields must be optional.
Knowledge-layer records (`ModelNode`, …) are in `src/models/knowledge.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from bmwow.knowledge.records import (
    FeedbackAspect,
    FeedbackClassification,
    FeedbackRetrieval,
    QualifiedRecord,
)
from bmwow.ontology.models import Measurement
from pydantic import BaseModel, Field

from .knowledge import ModelNode

Confidence = Literal["low", "medium", "high"]
AgentName = Literal["baseline", "competition", "feedback", "trends"]
AGENT_NAMES: tuple[AgentName, ...] = ("baseline", "competition", "feedback", "trends")

EXCERPT_MAX_CHARS = 1200


class Source(QualifiedRecord):
    id: str  # "kg:<node_id>", "sql:<query_hash>", "web:<url_hash8>", "fb:<item_id>"
    kind: Literal["ontology", "sql", "web", "feedback"]
    ref: str  # node id / SQL text / URL / feedback item id
    title: str = ""
    excerpt: str  # exact text or rendered row the claim relies on (<= 1200 chars). REQUIRED.
    retrieved_at: datetime
    measurement: Measurement | None = None
    availability: str | None = None
    epistemic_status: str | None = None
    classifications: list[FeedbackClassification] = Field(default_factory=list)
    aspects: list[FeedbackAspect] = Field(default_factory=list)
    retrieval: FeedbackRetrieval | None = None
    imported_at: datetime | None = None
    engine_type: str | None = None
    model_codes: list[str] = Field(default_factory=list)
    publication_label: str | None = None


class Quantity(BaseModel):
    value: float
    unit: str  # canonical: "km", "kW", "min", "EUR", "units", "share", ...
    qualifier: str = ""  # "WLTP", "10-80%", "2024 DE", "median", ...
    # Optional addition: where the number comes from. Set by code only, never copied from LLM output.
    # record = a structured ontology/SQL value, computed = derived by code from stored data,
    # source_text = must appear verbatim in a cited excerpt (checked by src/agent/validation.py).
    origin: Literal["record", "computed", "source_text"] = "source_text"


class Finding(BaseModel):
    id: str  # "F-<agent>-<n>", assigned by code, never by the LLM
    agent: AgentName
    attribute: str  # taxonomy key or "unmapped:<proposed_name>"
    claim: str  # one sentence, one claim
    polarity: Literal["positive", "negative", "neutral", "demand"]  # demand = customers want more
    subject: str  # "previous_model", "<competitor model>", "market", "customers"
    quantity: Quantity | None = None
    source_ids: list[str]  # >= 1, must resolve to Sources in the same report
    confidence: Confidence
    weight: float = 1.0  # set by code only (e.g. share of feedback items)


class AgentReport(BaseModel):
    agent: AgentName
    status: Literal["ok", "partial", "failed"]
    findings: list[Finding] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    summary: str = ""  # <= 120 words, for the UI
    stats: dict[str, float | int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class AnalysisRequest(BaseModel):
    """What the PM enters (§3.1). Validated against the model registry and region list (§4.4–4.5)."""

    model_code: str  # reference model; must be in the model registry: G60, F70, G68
    regions: list[str] | None = (
        None  # e.g. ["EU"], ["EU", "US"]; None/empty = all regions the model has data for
    )


class SearchLocale(BaseModel):
    country: str  # e.g. "de"
    lang: str  # e.g. "en"


class SupportedModel(BaseModel):
    """One model registry entry (§4.5); feeds the UI dropdowns."""

    model_code: str
    name: str
    regions: list[str]


class ProductBrief(BaseModel):
    """What the run actually uses, resolved from an `AnalysisRequest` by `resolve_request`."""

    reference_model: ModelNode  # from get_model(model_code): name, segment, powertrain, attributes
    regions: list[str]  # validated region codes
    markets: list[str]  # markets the regions expand to (as used in sales and feedback data)
    segment: str  # from reference_model
    competitors: list[ModelNode] = Field(
        default_factory=list
    )  # each tagged with its regions in this run
    focus_areas: list[str] = Field(
        default_factory=list
    )  # taxonomy areas to emphasize; empty = all (PM may set
    # them in a corrected brief via service.start_analysis(brief_override=...))
    search_locale: dict[str, SearchLocale] = Field(
        default_factory=dict
    )  # region -> web-search locale
    # Optional additions: region -> its markets (per-region shares), and resolution notes for the UI.
    region_markets: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @property
    def model_code(self) -> str:
        return self.reference_model.model_code or self.reference_model.node_id

    def region_of(self, market: str | None) -> str | None:
        for region, markets in self.region_markets.items():
            if market in markets:
                return region
        return None


class OntologyPersistence(BaseModel):
    """Optional ontology write outcome, independent of analysis completion and human review."""

    status: Literal["skipped", "stored", "failed"]
    error: str | None = None


class SituationAnalysis(BaseModel):  # the hand-off object
    run_id: str
    request: AnalysisRequest  # what the PM typed
    brief: ProductBrief  # what the run actually used
    reports: dict[AgentName, AgentReport]  # all four keys always present
    created_at: datetime
    # None means no outcome was recorded, including analyses saved before this field existed.
    ontology_persistence: OntologyPersistence | None = None
