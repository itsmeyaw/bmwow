"""Situation-analysis DTOs, distinct from persisted ontology Evidence/Signal objects.

Knowledge read records are defined in bmwow.knowledge.records. This module owns
analysis-only definitions and retains its existing import and wire names.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from bmwow.knowledge.records import (
    FeedbackAspect,
    FeedbackClassification,
    FeedbackRetrieval,
    ModelNode,
    QualifiedRecord,
)
from bmwow.knowledge.types import SearchLocale as SearchLocale
from bmwow.ontology.models import (
    AssessedConfidenceLevel,
    CapabilityAvailability,
    EpistemicStatus,
    Measurement,
)

Confidence = AssessedConfidenceLevel
# Analysis intent includes demand; this is not the ontology's SignalSentiment.
Polarity = Literal["positive", "negative", "neutral", "demand"]
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
    availability: CapabilityAvailability | None = None
    epistemic_status: EpistemicStatus | None = None
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
    # source_text = must appear verbatim in a cited excerpt (checked by bmwow/agent/validation.py).
    origin: Literal["record", "computed", "source_text"] = "source_text"


Direction = Literal["problem", "request", "strength", "neutral"]
TrendHorizon = Literal["now", "1-2y", "3y+"]
AvailabilityStatus = Literal["ok", "partial", "unavailable"]


class RegionTest(BaseModel):
    """Two-proportion z-test of one region's share against the other requested regions combined."""

    other: str  # e.g. "US" or "US+RoW"
    other_k: int
    other_n: int
    p_value: float


class FindingStats(BaseModel):
    """How certain a computed share is. Set by code only."""

    k: int  # items with the observation
    n: int  # items in the denominator
    denominator_label: str  # e.g. "BEV+PHEV feedback items, EU"
    ci_low: float  # Wilson 95% interval of k / n
    ci_high: float
    thin: bool  # small sample: n or k below the thresholds in rules.yaml
    region_test: RegionTest | None = None


class Finding(BaseModel):
    id: str  # "F-<agent>-<n>", assigned by code, never by the LLM
    agent: AgentName
    attribute: str  # taxonomy key or "unmapped:<proposed_name>"
    claim: str  # one sentence, one claim
    polarity: Polarity  # demand = customers want more; separate from sentiment
    subject: str  # "previous_model", "<competitor model>", "market", "customers"
    quantity: Quantity | None = None
    source_ids: list[str]  # >= 1, must resolve to Sources in the same report
    confidence: Confidence
    weight: float = 1.0  # set by code only (e.g. share of feedback items)
    # Optional additions (set by code): the region a finding is about (None = all requested regions),
    # its direction from the customer's view, statistics for computed shares, a trend's horizon and
    # the number of independent sources behind it.
    region: str | None = None
    direction: Direction | None = None
    stats: FindingStats | None = None
    horizon: TrendHorizon | None = None
    n_independent_sources: int | None = None


class Availability(BaseModel):
    """Whether a data source could be used in this run; missing data is reported, not hidden."""

    source: str  # e.g. "feedback", "feedback:CN", "sales", "studies", "web"
    status: AvailabilityStatus
    reason: str = ""


class SubTheme(BaseModel):
    """What exactly customers mean within one feature and direction."""

    attribute: str
    direction: Direction
    name: str
    k: int  # items in this sub-theme (method="llm": within the sample)
    of: int  # items of the feature and direction (method="llm": sample size)
    method: Literal["aspect_term", "llm"]
    source_ids: list[str]  # representative feedback items


class CandidateFeature(BaseModel):
    """A recurring topic that maps to no known feature: an open signal for review."""

    name: str
    k: int
    n: int
    source_ids: list[str]


class AgentReport(BaseModel):
    agent: AgentName
    status: Literal["ok", "partial", "failed"]
    findings: list[Finding] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    summary: str = ""  # <= 120 words, for the UI
    stats: dict[str, float | int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    # Optional additions: data availability, sub-themes and open signals (feedback).
    availability: list[Availability] = Field(default_factory=list)
    sub_themes: list[SubTheme] = Field(default_factory=list)
    candidates: list[CandidateFeature] = Field(default_factory=list)


class AnalysisRequest(BaseModel):
    """What the PM enters (§3.1). Validated against the model registry and region list (§4.4–4.5)."""

    model_code: str  # reference model; must be in the model registry: G60, F70, G68
    regions: list[str] | None = (
        None  # e.g. ["EU"], ["EU", "US"]; None/empty = all regions the model has data for
    )


class SupportedModel(BaseModel):
    """One model registry entry (§4.5); feeds the UI dropdowns."""

    model_code: str
    name: str
    regions: list[str]


class ProductBrief(BaseModel):
    """What the run actually uses, resolved from an `AnalysisRequest` by `resolve_request`."""

    reference_model: ModelNode  # from get_model(model_code): name, segment, powertrain, attributes
    regions: list[str]  # validated region codes
    markets: list[str]  # feedback query selectors; source sales/studies retain their own regions
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


# ---------------------------------------------------------------- structure_agent (per feature)


class FactRef(BaseModel):
    """One fact of a package, rendered by code, with the finding it comes from."""

    finding_id: str
    agent: AgentName
    subject: str
    text: str


class ValueComparison(BaseModel):
    """Competitor values of one feature that are comparable (same unit, condition and region)."""

    unit: str
    condition: str  # test standard / qualifier, e.g. "WLTP"; values under different ones never mix
    region: str | None
    n: int
    minimum: float
    median: float
    maximum: float
    lower_is_better: bool
    ours: float | None = None
    ours_rank: int | None = None  # 1 = best among competitors + ours
    field_size: int | None = None
    ours_vs_median: float | None = None  # (ours - median) / |median|
    finding_ids: list[str] = Field(default_factory=list)


class CustomerSignal(BaseModel):
    finding_id: str
    direction: Direction
    region: str | None
    share: float
    k: int
    n: int
    ci_low: float
    ci_high: float
    thin: bool
    differs_from: str | None = None  # other regions, when the region test is significant
    p_value: float | None = None


class TrendSignal(BaseModel):
    finding_id: str
    claim: str
    polarity: Polarity
    horizon: TrendHorizon | None
    n_independent_sources: int | None
    thin: bool


class Quote(BaseModel):
    source_id: str
    direction: Direction | None
    text: str


class EvidencePackage(BaseModel):
    """Everything the four agents found about one feature, as facts. No verdict: structure_agent's
    judgment reads this, and its guard checks the judgment against it."""

    attribute: str
    label: str
    importance: float  # ranking only: largest CI lower bound of a customer problem/request share
    ours: list[FactRef] = Field(default_factory=list)
    competitor_values: list[ValueComparison] = Field(default_factory=list)
    competitor_facts: list[FactRef] = Field(default_factory=list)
    customers: list[CustomerSignal] = Field(default_factory=list)
    sub_themes: list[SubTheme] = Field(default_factory=list)
    trends: list[TrendSignal] = Field(default_factory=list)
    comparisons: list[str] = Field(default_factory=list)  # factual sentences computed by code
    quotes: list[Quote] = Field(default_factory=list)  # representative and counter-evidence
    coverage: list[str] = Field(default_factory=list)  # missing views and data availability
    finding_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


Assessment = Literal["gap", "strength", "hygiene_factor", "demand", "unclear", "not_assessed"]


class GuardCheck(BaseModel):
    rule: str
    ok: bool
    detail: str = ""


class FeatureAssessment(BaseModel):
    """structure_agent's judgment of one feature, checked by code against its evidence package."""

    attribute: str
    assessment: Assessment
    what_exactly: str = ""  # the concrete issue or wish, e.g. a sub-theme
    widespread: Literal["widespread", "limited", "unclear"] = "unclear"
    certainty: Confidence = "low"
    brand_or_safety_relevant: bool = False
    reasoning: str = ""
    cited_ids: list[str] = Field(default_factory=list)
    guard: list[GuardCheck] = Field(default_factory=list)
    guard_status: Literal["passed", "revised", "flagged", "skipped"] = "skipped"
    note: str = ""  # why the feature was not assessed, if so


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
    # Optional additions from structure_agent: one evidence package and one assessment per feature.
    evidence_packages: list[EvidencePackage] = Field(default_factory=list)
    feature_assessments: list[FeatureAssessment] = Field(default_factory=list)
