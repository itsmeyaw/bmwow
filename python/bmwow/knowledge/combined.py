"""Ontology reads and query-based feedback behind the existing v1 interface."""

from urllib.parse import unquote

from bmwow.ontology.models import Context

from .config import KnowledgeConfig, VfcMapping
from .feedback import DataAvailability, FeedbackKnowledgeService, FeedbackRepository
from .geography import feedback_country_markets, feedback_region_markets
from .records import FeedbackAspect, FeedbackFilter, FeedbackItem, FeedbackPage, FeedbackRetrieval
from .repository import SnapshotRepository
from .service import KnowledgeService


class CombinedKnowledgeService(KnowledgeService):
    """Graph identity is canonical. Feedback scope, counts, and original citations stay intact."""

    def __init__(
        self,
        repository: SnapshotRepository,
        config: KnowledgeConfig,
        feedback_repository: FeedbackRepository,
        feedback_models: dict[str, str],
    ) -> None:
        super().__init__(repository, config)
        self._feedback = FeedbackKnowledgeService(feedback_repository)
        self._feedback_models = dict(feedback_models)
        self._feedback_coverage = [
            item.model_copy(deep=True) for item in feedback_repository.coverage()
        ]
        if any(node_id not in self._models for node_id in self._feedback_models.values()):
            raise ValueError("Feedback model mapping references an unknown canonical model")
        if len(set(self._feedback_models.values())) != len(self._feedback_models):
            raise ValueError("Feedback Derivates must map to distinct canonical models")
        graph_ids = set(self._nodes)
        dataset = feedback_repository.dataset()
        if dataset.source_id in graph_ids or any(
            node_id.startswith(
                (f"evidence:{dataset.dataset_key}:", f"aspect:{dataset.dataset_key}:")
            )
            for node_id in graph_ids
        ):
            raise ValueError("Graph and SQL citation namespaces overlap")

    def _coverage(self, model_id: str) -> dict[str, list[str]]:
        result = super()._coverage(model_id)
        countries = [
            country
            for item in self._feedback_coverage
            if self._feedback_models.get(item.derivate) == model_id
            for country in item.countries
        ]
        if countries:
            result["feedback_dataset"] = sorted(
                set(result.get("feedback_dataset", [])) | set(feedback_region_markets(countries))
            )
        return result

    def list_regions(self) -> dict[str, dict]:
        # Only an explicit source country definition may contribute countries to a query group.
        result = {}
        for market in self._markets.values():
            code = market.properties.code
            if code not in self._config.search_locales:
                continue
            entry = result.setdefault(
                code,
                {
                    "markets": [],
                    "search": self._config.search_locales[code].model_dump(),
                },
            )
            entry["markets"] = sorted(set(entry["markets"]) | set(market.properties.country_codes))
        grouped = feedback_region_markets(
            country for item in self._feedback_coverage for country in item.countries
        )
        for code, countries in grouped.items():
            entry = {
                "markets": countries,
                "search": {"country": countries[0].lower(), "lang": "en"},
            }
            if code not in result:
                result[code] = entry
            else:
                result[code]["markets"] = sorted(
                    set(result[code]["markets"]) | set(entry["markets"])
                )
        for code, entry in result.items():
            if not entry["markets"]:
                # An empty country selector means unrestricted SQL. Retain the explicit query
                # alias for a source-only region, so missing feedback never becomes worldwide.
                entry["markets"] = [code]
        return dict(sorted(result.items()))

    def _feedback_context(self, context: Context | None, model_code: str | None) -> Context | None:
        if context is None:
            return None
        context = context.model_copy(deep=True)
        canonical = self._feedback_models.get(model_code or "")
        context.vehicle_model_ids = [canonical] if canonical else []
        # Original countries remain authoritative; source sales/study market IDs are not added.
        context.market_ids = []
        return context

    def _feedback_item(self, item: FeedbackItem) -> FeedbackItem:
        item = item.model_copy(deep=True)
        item.context = self._feedback_context(item.context, item.model)
        if item.model not in self._feedback_models:
            item.limitations.append("Feedback Derivate has no reviewed canonical model mapping.")
        for aspect in item.aspects:
            aspect.context = self._feedback_context(aspect.context, item.model)
            mappings = (
                self._config.aspect_mappings
                if aspect.extraction_source == "llm"
                else self._config.vfc_mappings
            )
            mapping = mappings.get(aspect.aspect_term or "")
            aspect.mapping_status = mapping.status if mapping else None
            aspect.attribute = self._config.mapped_feature(mapping)
        for classification in item.classifications:
            # SQL does not retain a combined VFC string; use an explicit exact-term mapping.
            mapping = self._config.vfc_mappings.get(classification.vfc_combined or "")
            if mapping is None:
                mapping = self._config.vfc_mappings.get(classification.aspect_term or "")
            classification.mapping_status = mapping.status if mapping else None
            classification.attribute = self._config.mapped_feature(mapping)
        return item

    def get_feedback_page(self, filters: FeedbackFilter) -> FeedbackPage:
        filters = filters.model_copy(deep=True)
        if filters.models:
            wanted = {
                model.id
                for value in filters.models
                if (model := self._find_model(value)) is not None
            }
            codes = [code for code, node_id in self._feedback_models.items() if node_id in wanted]
            if not codes:
                return FeedbackPage(
                    retrieval=FeedbackRetrieval(
                        total_matching=0,
                        returned_count=0,
                        truncated=False,
                        selection_policy="No selected model has a configured SQL Derivate identity.",
                    )
                )
            filters.models = codes
        filters.markets = feedback_country_markets(filters.markets)
        page = self._feedback.get_feedback_page(filters)
        page.items = [self._feedback_item(item) for item in page.items]
        return page

    def get_feedback_items(self, filters: FeedbackFilter) -> list[FeedbackItem]:
        return self.get_feedback_page(filters).items

    def get_aspect_mapping(self, citation_id: str) -> VfcMapping | None:
        """Explicit proposed/reviewed mapping metadata; original aspect labels stay unchanged."""
        aspect = self._feedback.resolve_citation(citation_id)
        if not isinstance(aspect, FeedbackAspect):
            return None
        mappings = (
            self._config.aspect_mappings
            if aspect.extraction_source == "llm"
            else self._config.vfc_mappings
        )
        mapping = mappings.get(aspect.aspect_term or "")
        return mapping.model_copy(deep=True) if mapping else None

    def get_data_availability(self) -> list[DataAvailability]:
        source_kinds = {
            self._source(node).properties.source_kind
            for node in self._bundle.nodes
            if node.type == "Evidence"
        }
        result = [
            DataAvailability(kind="feedback", status="available", reason="SQL feedback reads.")
        ]
        for kind, source_kind in (
            ("sales", "sales_dataset"),
            ("studies", "customer_study"),
            ("capabilities", "product_catalog"),
        ):
            available = source_kind in source_kinds
            result.append(
                DataAvailability(
                    kind=kind,
                    status="available" if available else "unavailable",
                    reason="Connected source evidence."
                    if available
                    else "No connected source evidence.",
                )
            )
        return result

    def resolve_citation(self, citation_id: str):
        value = citation_id[3:] if citation_id.startswith(("kg:", "fb:")) else citation_id
        if value.startswith("vehicle:feedback:"):
            node_id = self._feedback_models.get(unquote(value[len("vehicle:feedback:") :]))
            return self.get_model(node_id) if node_id else None
        if value in self._nodes:
            return super().resolve_citation(value)
        result = self._feedback.resolve_citation(value)
        if isinstance(result, FeedbackItem):
            return self._feedback_item(result)
        if isinstance(result, FeedbackAspect) and result.context is not None:
            ids = result.context.vehicle_model_ids
            code = (
                unquote(ids[0][len("vehicle:feedback:") :])
                if len(ids) == 1 and ids[0].startswith("vehicle:feedback:")
                else None
            )
            result.context = self._feedback_context(result.context, code)
        return result
