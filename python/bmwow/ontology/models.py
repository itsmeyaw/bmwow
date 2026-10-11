"""Canonical Pydantic models for the v0.2.0 product decision ontology.

All nullable fields remain required: an explicit null records missing information.
Use model_validate_json for wire payloads so strict dates accept ISO JSON strings.
Graph-wide rules live in validation.py and are not implied by JSON Schema alone.
"""

from datetime import date
from typing import Annotated, Literal, TypeVar, get_args

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)
from rfc3986_validator import validate_rfc3986

OntologyVersion = Literal["0.2.0"]
ONTOLOGY_VERSION = get_args(OntologyVersion)[0]

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Id = Annotated[Text, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*:[^\s]+$")]
CountryCode = Annotated[Text, StringConstraints(pattern=r"^[A-Z]{2}$")]
PartialDate = Annotated[Text, StringConstraints(pattern=r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")]
ContentHash = Annotated[Text, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
PositiveInt = Annotated[int, Field(ge=1)]
NonnegativeInt = Annotated[int, Field(ge=0)]
ModelYear = Annotated[int, Field(ge=1900, le=2200)]

Domain = Literal[
    "exterior",
    "interior",
    "powertrain",
    "driver_assistance",
    "digital_experience",
    "ownership_experience",
    "cross_domain",
    "unknown",
]
EngineType = Literal["ice", "phev", "bev", "unknown"]
SignalKind = Literal[
    "customer_feedback",
    "public_sentiment",
    "competitor_capability",
    "product_capability",
    "study_finding",
    "commercial_indicator",
    "trend_indicator",
]
AssessedConfidenceLevel = Literal["low", "medium", "high"]
ConfidenceLevel = Literal[AssessedConfidenceLevel, "unassessed"]
CapabilityAvailability = Literal[
    "announced", "standard", "optional", "available_unspecified", "unavailable", "unknown"
]
EpistemicStatus = Literal[
    "reported_experience", "opinion", "publisher_claim", "inference", "forecast"
]
SignalSentiment = Literal["positive", "negative", "mixed", "neutral", "unknown", "not_applicable"]
RelationshipType = Literal[
    "IN_SOURCE",
    "DERIVED_FROM",
    "CONCERNS",
    "SUPPORTS",
    "CHALLENGES",
    "ADDRESSES",
    "JUSTIFIED_BY",
    "DEPENDS_ON",
    "REVIEWS",
    "COMPETES_WITH",
    "SUPERSEDES",
    "DESCRIBES",
    "INCLUDES",
    "BASELINED_ON",
    "IS_VARIANT_OF",
]
NodeType = Literal[
    "SourceDocument",
    "VehicleModel",
    "Market",
    "Feature",
    "CatalogItem",
    "Evidence",
    "Signal",
    "CustomerNeed",
    "Trend",
    "Assumption",
    "Requirement",
    "Decision",
]

T = TypeVar("T")


def _unique[T](values: list[T]) -> list[T]:
    if len(values) != len(set(values)):
        raise ValueError("items must be unique")
    return values


UniqueList = Annotated[
    list[T], AfterValidator(_unique), Field(json_schema_extra={"uniqueItems": True})
]


def _http_url(value: str) -> str:
    # Match JSON Schema's URI format without normalizing the captured source URL.
    if not validate_rfc3986(value, rule="URI"):
        raise ValueError("source URL must be a valid URI")
    return value


HttpUrlText = Annotated[
    Text,
    StringConstraints(pattern=r"^https?://"),
    AfterValidator(_http_url),
    Field(json_schema_extra={"format": "uri"}),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Context(ContractModel):
    """Explicit observation scope; empty lists mean unknown, never universal coverage."""

    vehicle_model_ids: UniqueList[Id] = Field(description="Exact known model or variant IDs.")
    market_ids: UniqueList[Id] = Field(description="Configured market IDs; no inferred membership.")
    country_codes: UniqueList[CountryCode]
    engine_types: UniqueList[EngineType]
    as_of: date | None
    scope_notes: list[Text]


class Uncertainty(ContractModel):
    level: ConfidenceLevel
    reason: Text
    limitations: list[Text]


class Provenance(ContractModel):
    actor_type: Literal["human", "software"]
    actor_id: Text
    method: Literal[
        "provided_annotation",
        "manual_interpretation",
        "llm_extraction",
        "rule_mapping",
        "quantitative_aggregation",
    ]
    created_at: AwareDatetime
    model: Text | None
    prompt_version: Text | None


class Period(ContractModel):
    label: Text
    start: date | None
    end: date | None


class Scale(ContractModel):
    minimum: float
    maximum: float


class NumericRange(ContractModel):
    """A source-reported interval; configuration alternatives remain separate observations."""

    minimum: float
    maximum: float


class Measurement(ContractModel):
    """Original scalar or interval with conditions needed for meaningful comparisons."""

    metric: Text
    value: float | None = Field(description="Scalar only; null when value_range is populated.")
    value_range: NumericRange | None = Field(
        description="Genuine interval only; null for a scalar. Never compute a midpoint."
    )
    unit: Text
    statistic: Literal["count", "mean", "proportion", "percent", "index", "scalar"]
    temporal_status: Literal["historical", "source_reported_future", "forecast", "unknown"]
    period: Period | None
    sample_size: NonnegativeInt | None
    denominator: Annotated[float, Field(gt=0)] | None
    scale: Scale | None
    comparison_basis: Text | None
    population: Text | None
    test_standard: Text | None = Field(
        description="Original procedure, e.g. WLTP; null if unknown."
    )
    conditions: list[Text] = Field(
        description="Configuration, environment and footnote constraints."
    )
    question: Text | None = Field(description="Original survey question, when applicable.")
    response_category: Text | None = Field(
        description="Original response label; no scale conversion."
    )
    notes: list[Text]


class SpreadsheetLocator(ContractModel):
    kind: Literal["spreadsheet"]
    sheet: Text
    range: Annotated[Text, StringConstraints(pattern=r"^[A-Z]+[1-9][0-9]*(?::[A-Z]+[1-9][0-9]*)?$")]


class CsvLocator(ContractModel):
    kind: Literal["csv"]
    row: Annotated[int, Field(ge=2)]
    columns: Annotated[list[Text], Field(min_length=1)]


class SqlLocator(ContractModel):
    kind: Literal["sql"]
    table: Text
    record_key: Text
    original_locator: Text | None


class PdfLocator(ContractModel):
    kind: Literal["pdf"]
    page: PositiveInt
    section: Text | None


class WebLocator(ContractModel):
    kind: Literal["web"]
    selector: Text | None
    text_fragment: Text


Locator = Annotated[
    SpreadsheetLocator | CsvLocator | SqlLocator | PdfLocator | WebLocator,
    Field(discriminator="kind"),
]


class Classification(ContractModel):
    feedback_type: Text | None
    vfc_level2: Text | None
    vfc_level3: Text | None
    vfc_combined: Text | None
    locator: Locator


class PublicContext(ContractModel):
    platform: Text
    author_role: Literal["owner", "prospective_buyer", "reviewer", "unknown"]
    ownership_verified: bool | None
    sampling_method: Literal["targeted_search", "platform_api", "manual_selection", "unknown"]
    sampling_notes: Annotated[list[Text], Field(min_length=1)]


class AvailabilityCondition(ContractModel):
    """Inspectable constraints; all/any semantics must not be flattened into unconditional links."""

    kind: Literal["requires_all", "requires_any", "excludes", "configuration", "usage", "unknown"]
    catalog_item_ids: UniqueList[Id] = Field(
        description="Item references for requires_all/requires_any/excludes; empty for other kinds."
    )
    description: Text = Field(description="Preserve the condition and original unresolved details.")


class Capability(ContractModel):
    """One evidenced offering or performance claim; identity and customer demand are separate."""

    availability: CapabilityAvailability
    variant: Text | None
    measurement: Measurement | None
    conditions: list[AvailabilityCondition]
    notes: list[Text]


class Criterion(ContractModel):
    """A customer acceptance test; unknown thresholds remain explicit rather than fabricated."""

    description: Text
    metric: Text | None
    operator: Literal[">=", "<=", "=", ">", "<"] | None
    target: float | None
    unit: Text | None
    basis: Literal["proposed_target", "evidence_supported_target", "human_set_target"]
    supporting_evidence_ids: UniqueList[Id]
    verification_method: Literal[
        "user_study", "benchmark_test", "inspection", "analysis", "to_be_defined"
    ]
    test_conditions: list[Text]


class LocalFileLocation(ContractModel):
    kind: Literal["local_file"]
    path: Text


class WebLocation(ContractModel):
    kind: Literal["web"]
    url: HttpUrlText


class SqlLocation(ContractModel):
    kind: Literal["sql"]
    database_alias: Text
    table: Text


SourceLocation = Annotated[
    LocalFileLocation | WebLocation | SqlLocation, Field(discriminator="kind")
]


class SourceDocumentProperties(ContractModel):
    source_kind: Literal[
        "feedback_dataset",
        "customer_study",
        "sales_dataset",
        "product_catalog",
        "public_discussion",
        "editorial_review",
        "competitor_official",
        "industry_report",
        "global_indicator",
    ]
    origin: Literal["provided_bmw", "external", "synthetic"]
    location: SourceLocation
    publisher: Text | None
    publication_date: PartialDate | None
    retrieved_at: AwareDatetime
    content_hash: ContentHash | None
    source_role: Literal["primary", "secondary", "informal", "unknown"]
    independence_group: Text | None
    access: Literal["provided_internal", "public"]
    quality_notes: list[Text]


class VehicleModelProperties(ContractModel):
    brand: Text
    vehicle_line: Text
    generation_code: Text | None
    model_year: ModelYear | None
    variant: Text | None
    aliases: UniqueList[Text]


class MarketProperties(ContractModel):
    code: Text
    name: Text
    country_codes: UniqueList[CountryCode]
    definition_notes: Annotated[list[Text], Field(min_length=1)]


class FeatureProperties(ContractModel):
    definition: Text
    domains: Annotated[UniqueList[Domain], Field(min_length=1)]
    aliases: UniqueList[Text]


class CatalogItemProperties(ContractModel):
    item_kind: Literal["equipment", "package"]
    equipment_code: Text | None
    description: Text
    context: Context
    conditions: list[AvailabilityCondition]
    notes: list[Text]
    provenance: Provenance


class EvidenceProperties(ContractModel):
    record_key: Text
    dedup_key: Text
    source_channel: Text | None
    locator: Locator
    raw_text: Text | None
    measurement: Measurement | None
    raw_classifications: list[Classification]
    context: Context
    limitations: list[Text]


class TextEvidenceProperties(EvidenceProperties):
    evidence_kind: Literal["feedback_record", "catalog_excerpt", "web_excerpt"]
    raw_text: Text


class StatisticEvidenceProperties(EvidenceProperties):
    evidence_kind: Literal["study_statistic", "sales_statistic"]
    measurement: Measurement


EvidencePayload = Annotated[
    TextEvidenceProperties | StatisticEvidenceProperties, Field(discriminator="evidence_kind")
]


class ExtractionConfidence(ContractModel):
    level: ConfidenceLevel
    reason: Text


class SignalProperties(ContractModel):
    statement: Text
    epistemic_status: EpistemicStatus
    sentiment: SignalSentiment
    context: Context
    public_context: PublicContext | None
    capability: Capability | None
    extraction_confidence: ExtractionConfidence
    provenance: Provenance


class GeneralSignalProperties(SignalProperties):
    signal_kind: Literal[
        "customer_feedback", "trend_indicator", "study_finding", "commercial_indicator"
    ]


class PublicSentimentProperties(SignalProperties):
    signal_kind: Literal["public_sentiment"]
    public_context: PublicContext


class CompetitorCapabilityProperties(SignalProperties):
    signal_kind: Literal["competitor_capability"]
    capability: Capability


class ProductCapabilityProperties(SignalProperties):
    signal_kind: Literal["product_capability"]
    capability: Capability


SignalPayload = Annotated[
    GeneralSignalProperties
    | PublicSentimentProperties
    | CompetitorCapabilityProperties
    | ProductCapabilityProperties,
    Field(discriminator="signal_kind"),
]


class CustomerNeedProperties(ContractModel):
    statement: Text
    context: Context
    uncertainty: Uncertainty
    provenance: Provenance


class Horizon(ContractModel):
    from_year: int
    to_year: int


class TrendProperties(ContractModel):
    statement: Text
    trend_kind: Literal["product", "technology", "societal", "economic", "environmental"]
    temporal_status: Literal["observed", "forecast", "mixed"]
    horizon: Horizon
    context: Context
    uncertainty: Uncertainty
    provenance: Provenance


class AssumptionProperties(ContractModel):
    statement: Text
    rationale: Text
    impact_if_false: Text
    validation_plan: Text
    status: Literal["unvalidated", "supported", "challenged"]
    context: Context
    provenance: Provenance


class RequirementProperties(ContractModel):
    statement: Text
    customer_value: Text
    context: Context
    scope_role: Literal["successor_of_baseline_models"]
    horizon_years: Annotated[int, Field(ge=3, le=5)]
    target_launch_year: ModelYear | None
    change_intent: Literal["introduce", "improve", "retain", "remove"]
    baseline_status: Literal["known_present", "known_absent", "unknown"]
    baseline_rationale: Text = Field(
        description="Why this change intent fits the evidenced baseline; unknown does not mean absent."
    )
    acceptance_criteria: Annotated[list[Criterion], Field(min_length=1)]
    prioritization_rationale: Text
    uncertainty: Uncertainty
    provenance: Provenance


class DecisionProperties(ContractModel):
    action: Literal["approve", "reject", "request_changes", "set_priority", "comment"]
    actor_type: Literal["human"]
    actor_id: Text
    decided_at: AwareDatetime
    requirement_revision: PositiveInt
    reason: Text
    priority: PositiveInt | None


class NodeBase(ContractModel):
    id: Id
    entity_key: Id
    label: Text
    revision: PositiveInt


class SourceDocument(NodeBase):
    """A specific file, SQL source, or captured web page; records origin, retrieval date, and independence."""

    type: Literal["SourceDocument"]
    properties: SourceDocumentProperties


class VehicleModel(NodeBase):
    """A BMW or competitor model scoped to generation, model year, and variant when known."""

    type: Literal["VehicleModel"]
    properties: VehicleModelProperties


class Market(NodeBase):
    """An explicitly defined market; country-to-market mappings are configured, never guessed."""

    type: Literal["Market"]
    properties: MarketProperties


class Feature(NodeBase):
    """A canonical capability or experience; VFC labels are source annotations and aliases."""

    type: Literal["Feature"]
    properties: FeatureProperties


class CatalogItem(NodeBase):
    """An option or package within one catalog edition; availability is an evidenced capability claim."""

    type: Literal["CatalogItem"]
    properties: CatalogItemProperties


class Evidence(NodeBase):
    """An original record, excerpt, or statistic with a source locator. Repeated classification rows remain one feedback record."""

    type: Literal["Evidence"]
    properties: EvidencePayload


class Signal(NodeBase):
    """One scoped interpretation: experience, sentiment, capability, study finding, commercial indicator or trend."""

    type: Literal["Signal"]
    properties: SignalPayload


class CustomerNeed(NodeBase):
    """A customer outcome synthesized from supporting and challenging signals."""

    type: Literal["CustomerNeed"]
    properties: CustomerNeedProperties


class Trend(NodeBase):
    """A time-scoped synthesis of indicators; projections remain labeled as forecasts."""

    type: Literal["Trend"]
    properties: TrendProperties


class Assumption(NodeBase):
    """An explicit unproven premise with its impact and a validation plan."""

    type: Literal["Assumption"]
    properties: AssumptionProperties


class Requirement(NodeBase):
    """A revisioned proposal for a successor vehicle, justified by evidence and reviewed separately by a human."""

    type: Literal["Requirement"]
    properties: RequirementProperties


class Decision(NodeBase):
    """An immutable human review event targeting one exact requirement revision."""

    type: Literal["Decision"]
    properties: DecisionProperties


Node = Annotated[
    SourceDocument
    | VehicleModel
    | Market
    | Feature
    | CatalogItem
    | Evidence
    | Signal
    | CustomerNeed
    | Trend
    | Assumption
    | Requirement
    | Decision,
    Field(discriminator="type"),
]


class Edge(ContractModel):
    id: Id
    type: RelationshipType
    source_id: Id
    target_id: Id
    rationale: Text
    context_transfer: Text | None


class GraphBundle(ContractModel):
    """A closed snapshot of typed nodes and relationships; also run graph validation."""

    ontology_version: OntologyVersion
    purpose: Literal["fixture", "sample", "production"]
    as_of: date
    description: Text
    nodes: Annotated[list[Node], Field(min_length=1)]
    edges: list[Edge]
