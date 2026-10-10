"""Query-based feedback reads; these projections are not persisted ontology objects."""

from __future__ import annotations

from typing import Literal, Protocol
from urllib.parse import quote, unquote

from pydantic import Field

from .config import Configuration, ModelProfile
from .geography import feedback_region_markets
from .records import FeedbackAspect, FeedbackFilter, FeedbackItem, FeedbackPage, ModelNode, Record


class FeedbackDataset(Record):
    source_id: str
    dataset_key: str
    source_version: str | None = None
    original_file_location: str | None = None
    limitations: list[str] = Field(default_factory=list)


class FeedbackCoverage(Record):
    derivate: str
    countries: list[str]
    engine_types: list[str]
    feedback_count: int = Field(ge=0)
    brand: str | None = None
    sales_description: str | None = None


class DataAvailability(Record):
    kind: str
    status: Literal["available", "unavailable"]
    reason: str


class FeedbackRepository(Protocol):
    """A replaceable read port alongside, rather than inside, SnapshotRepository."""

    def read_feedback(self, filters: FeedbackFilter) -> FeedbackPage: ...
    def coverage(self) -> list[FeedbackCoverage]: ...
    def dataset(self) -> FeedbackDataset: ...
    def find_feedback(self, feedback_explorer_id: str) -> FeedbackItem | None: ...
    def find_aspect(self, aspect_id: str) -> FeedbackAspect | None: ...


class FeedbackServiceConfig(Configuration):
    # Application curation, keyed by Derivate. None is inferred from feedback coverage.
    model_profiles: dict[str, ModelProfile] = Field(default_factory=dict)
    # Application search-language policy, not an inferred language of the Verbatim.
    research_language: str = Field(default="en", min_length=2)


class KnowledgeUnavailableError(RuntimeError):
    """The selected data backend cannot supply this kind of knowledge yet."""


def feedback_id(dataset_key: str, explorer_id: str) -> str:
    return f"evidence:{dataset_key}:{quote(explorer_id, safe='')}"


def aspect_id(dataset_key: str, sql_id: str) -> str:
    return f"aspect:{dataset_key}:{sql_id}"


def vehicle_id(derivate: str) -> str:
    return f"vehicle:feedback:{quote(derivate, safe='')}"


class FeedbackKnowledgeService:
    """Feedback-only v1 service. Graph knowledge is supplied by a separate backend."""

    def __init__(
        self, repository: FeedbackRepository, config: FeedbackServiceConfig | None = None
    ) -> None:
        self._repository = repository
        self._config = (config or FeedbackServiceConfig()).model_copy(deep=True)

    def get_feedback_page(self, filters: FeedbackFilter) -> FeedbackPage:
        return self._repository.read_feedback(filters).model_copy(deep=True)

    def get_feedback_items(self, filters: FeedbackFilter) -> list[FeedbackItem]:
        return self.get_feedback_page(filters).items

    def list_supported_models(self) -> list[dict]:
        return [
            {
                "model_code": item.derivate,
                "name": item.sales_description or item.derivate,
                "regions": sorted(feedback_region_markets(item.countries)),
            }
            for item in self._repository.coverage()
        ]

    def list_regions(self) -> dict[str, dict]:
        regions = feedback_region_markets(
            country for item in self._repository.coverage() for country in item.countries
        )
        return {
            region: {
                "markets": countries,
                "search": {
                    "country": countries[0].lower(),
                    "lang": self._config.research_language,
                },
            }
            for region, countries in sorted(regions.items())
        }

    def get_model(self, model_code: str) -> ModelNode | None:
        for item in self._repository.coverage():
            if model_code.strip().upper() not in {item.derivate, vehicle_id(item.derivate).upper()}:
                continue
            profile = self._config.model_profiles.get(item.derivate)
            regions = sorted(feedback_region_markets(item.countries))
            note = "Feedback coverage only; equipment and sale availability are not established."
            note += (
                f" {profile.curation_note}"
                if profile
                else " Segment is unknown until an application profile is curated."
            )
            return ModelNode(
                node_id=vehicle_id(item.derivate),
                model_code=item.derivate,
                name=item.sales_description or item.derivate,
                brand=item.brand or "unknown",
                segment=profile.segment if profile else "unknown",
                powertrain=profile.powertrain if profile else None,
                regions=regions,
                sold_regions=profile.sold_regions if profile else [],
                data_coverage={"feedback_dataset": regions},
                curation_note=note,
            )
        return None

    def get_data_availability(self) -> list[DataAvailability]:
        return [
            DataAvailability(kind="feedback", status="available", reason="SQL feedback reads.")
        ] + [
            DataAvailability(
                kind=kind, status="unavailable", reason=f"{kind} is not connected to this backend."
            )
            for kind in (
                "sales",
                "studies",
                "capabilities",
                "portfolio",
                "competitors",
                "documents",
            )
        ]

    def _unavailable(self, kind: str):
        raise KnowledgeUnavailableError(f"{kind} is not connected to the feedback-only backend.")

    def get_attribute_values(self, model_id: str, attributes: list[str] | None = None):
        return self._unavailable("Capabilities")

    def list_portfolio(self, segment: str | None = None, regions: list[str] | None = None):
        return self._unavailable("Portfolio")

    def list_competitor_models(self, segment: str, regions: list[str], names=None):
        # Required during v1 request resolution. Empty means no connected competitive selection;
        # availability and the reference's curation note explain the missing coverage.
        return []

    def search_documents(self, query: str, kinds=None, regions=None, k: int = 10):
        return self._unavailable("Documents")

    def sales_volume(self, models: list[str], markets=None, period_from=None, period_to=None):
        return self._unavailable("Sales")

    def get_study_scores(self, models: list[str], regions: list[str]):
        return self._unavailable("Studies")

    def get_taxonomy(self):
        # Coarse SQL buckets are not canonical Feature identities. v1 may use its configured YAML.
        return None

    def resolve_citation(self, citation_id: str):
        value = citation_id
        if value.startswith(("kg:", "fb:")):
            value = value[3:]
        dataset = self._repository.dataset()
        if value == dataset.source_id:
            return dataset
        if value.startswith("vehicle:feedback:"):
            return self.get_model(unquote(value[len("vehicle:feedback:") :]))
        prefix = f"evidence:{dataset.dataset_key}:"
        if value.startswith(prefix):
            return self._repository.find_feedback(unquote(value[len(prefix) :]))
        prefix = f"aspect:{dataset.dataset_key}:"
        if value.startswith(prefix):
            return self._repository.find_aspect(value[len(prefix) :])
        return None
