"""Deterministic projections of a closed ontology snapshot for situation analysis."""

from __future__ import annotations

import re
from datetime import date

from bmwow.ontology import GraphBundle, validate_bundle
from bmwow.ontology.models import (
    Context,
    Evidence,
    Feature,
    Market,
    Measurement,
    Signal,
    SourceDocument,
    VehicleModel,
)

from .config import KnowledgeConfig
from .records import (
    AttributeValue,
    DocChunk,
    EvidenceReference,
    FeedbackClassification,
    FeedbackFilter,
    FeedbackItem,
    ModelNode,
    SalesRow,
    StudyScore,
)
from .repository import SnapshotRepository


def measurement_text(measurement: Measurement) -> str:
    """Readable source view, retaining unknown survey and technical qualifications."""
    data = measurement.model_dump(mode="json")
    return "; ".join(f"{key}={value}" for key, value in data.items())


class KnowledgeService:
    """A read service over a fixed version; construct a new service for a new snapshot."""

    def __init__(self, repository: SnapshotRepository, config: KnowledgeConfig) -> None:
        bundle = repository.load_snapshot()
        errors = validate_bundle(bundle)
        if errors:
            raise ValueError("Invalid knowledge snapshot:\n" + "\n".join(errors))
        self._bundle = bundle.model_copy(deep=True)
        self._config = config.model_copy(deep=True)
        self._nodes = {node.id: node for node in self._bundle.nodes}
        self._edges = sorted(self._bundle.edges, key=lambda edge: edge.id)
        self._models = {
            node.id: node for node in self._bundle.nodes if isinstance(node, VehicleModel)
        }
        self._markets = {node.id: node for node in self._bundle.nodes if isinstance(node, Market)}
        self._check_config()

    @property
    def config(self) -> KnowledgeConfig:
        return self._config.model_copy(deep=True)

    def _check_config(self) -> None:
        for node_id in self._config.model_profiles:
            if node_id not in self._models:
                raise ValueError(f"Unknown model profile: {node_id}")
        for node_id in self._config.feature_keys:
            if not isinstance(self._nodes.get(node_id), Feature):
                raise ValueError(f"Unknown Feature: {node_id}")
        for mapping in (
            *self._config.vfc_mappings.values(),
            *self._config.study_mappings.values(),
            *self._config.aspect_mappings.values(),
        ):
            if mapping.feature_id not in self._config.feature_keys:
                raise ValueError(
                    f"Feature mapping needs a configured Feature key: {mapping.feature_id}"
                )
        codes = {market.properties.code for market in self._markets.values()}
        if set(self._config.search_locales) - codes:
            raise ValueError("Search locale has no corresponding Market")
        for profile in self._config.model_profiles.values():
            if set(profile.sold_regions) - codes:
                raise ValueError("Curated model availability has an unknown region")
        for evidence_id, group in self._config.sales_groups.items():
            evidence = self._nodes.get(evidence_id)
            if (
                not isinstance(evidence, Evidence)
                or evidence.properties.evidence_kind != "sales_statistic"
            ):
                raise ValueError(f"Sales group has no corresponding sales Evidence: {evidence_id}")
            if len(evidence.properties.context.vehicle_model_ids) < 2 or not group.strip():
                raise ValueError(
                    f"Sales group needs a combined-model observation and nonempty label: {evidence_id}"
                )

    def snapshot(self) -> GraphBundle:
        return self._bundle.model_copy(deep=True)

    def _targets(self, node_id: str, relationship: str) -> list[str]:
        return [
            edge.target_id
            for edge in self._edges
            if edge.source_id == node_id and edge.type == relationship
        ]

    def _source(self, evidence: Evidence) -> SourceDocument:
        return self._nodes[self._targets(evidence.id, "IN_SOURCE")[0]]

    def _references(self, node_id: str) -> list[EvidenceReference]:
        evidence_ids = (
            [node_id]
            if isinstance(self._nodes[node_id], Evidence)
            else self._targets(node_id, "DERIVED_FROM")
        )
        return [
            EvidenceReference(
                evidence_id=evidence.id,
                source_id=self._source(evidence).id,
                record_key=evidence.properties.record_key,
                locator=evidence.properties.locator,
            )
            for evidence_id in evidence_ids
            if isinstance(evidence := self._nodes[evidence_id], Evidence)
        ]

    def _find_model(self, value: str) -> VehicleModel | None:
        key = value.strip().casefold()
        if not key:
            return None
        matches = [
            model
            for model in self._models.values()
            if key
            in {
                model.id.casefold(),
                model.label.casefold(),
                (model.properties.generation_code or "").casefold(),
                *(alias.casefold() for alias in model.properties.aliases),
            }
        ]
        if len(matches) > 1:
            generations = [model for model in matches if model.properties.variant is None]
            if len(generations) == 1:
                return generations[0]
            raise ValueError(f"Ambiguous model identity: {value}")
        return matches[0] if matches else None

    def _regions(self, context: Context) -> list[str]:
        # Explicit market IDs are authoritative. Country fallback uses configured membership only.
        if context.market_ids:
            return sorted(
                {self._markets[node_id].properties.code for node_id in context.market_ids}
            )
        return sorted(
            {
                market.properties.code
                for market in self._markets.values()
                if set(context.country_codes) & set(market.properties.country_codes)
            }
        )

    def _coverage(self, model_id: str) -> dict[str, list[str]]:
        result: dict[str, set[str]] = {}
        for evidence in self._bundle.nodes:
            if not isinstance(evidence, Evidence):
                continue
            if model_id in evidence.properties.context.vehicle_model_ids:
                kind = self._source(evidence).properties.source_kind
                result.setdefault(kind, set()).update(self._regions(evidence.properties.context))
        return {kind: sorted(regions) for kind, regions in sorted(result.items())}

    def get_model(self, model_code: str) -> ModelNode | None:
        model = self._find_model(model_code)
        if model is None:
            return None
        profile = self._config.model_profiles.get(model.id)
        if profile is None:
            raise ValueError(f"Model {model.id} needs a reviewed segment profile before v1 use")
        coverage = self._coverage(model.id)
        return ModelNode(
            node_id=model.id,
            model_code=model.properties.generation_code,
            name=model.label,
            brand=model.properties.brand,
            segment=profile.segment,
            powertrain=profile.powertrain,
            regions=sorted({region for regions in coverage.values() for region in regions}),
            sold_regions=profile.sold_regions,
            data_coverage=coverage,
            curation_note=profile.curation_note,
            attributes=self.get_attribute_values(model.id),
        ).model_copy(deep=True)

    def list_supported_models(self) -> list[dict]:
        result = []
        for model in sorted(self._models.values(), key=lambda node: node.id):
            if (
                model.properties.brand.casefold() != "bmw"
                or model.properties.variant is not None
                or model.id not in self._config.model_profiles
            ):
                continue
            record = self.get_model(model.id)
            if record.regions and record.model_code:
                result.append(
                    {
                        "model_code": record.model_code,
                        "name": record.name,
                        "regions": record.regions,
                    }
                )
        return result

    def list_regions(self) -> dict[str, dict]:
        return {
            market.properties.code: {
                "markets": list(market.properties.country_codes),
                "search": self._config.search_locales[market.properties.code].model_dump(),
            }
            for market in sorted(self._markets.values(), key=lambda node: node.id)
            if market.properties.code in self._config.search_locales
        }

    def list_portfolio(
        self, segment: str | None = None, regions: list[str] | None = None
    ) -> list[ModelNode]:
        result = []
        for model in sorted(self._models.values(), key=lambda node: node.id):
            profile = self._config.model_profiles.get(model.id)
            if model.properties.brand.casefold() != "bmw" or profile is None:
                continue
            if model.properties.variant is not None:
                continue
            if segment is not None and profile.segment != segment:
                continue
            if not profile.sold_regions or (
                regions and not set(regions) & set(profile.sold_regions)
            ):
                continue
            result.append(self.get_model(model.id))
        return [record.model_copy(deep=True) for record in result]

    def list_competitor_models(
        self, segment: str, regions: list[str], names: list[str] | None = None
    ) -> list[ModelNode]:
        # A profile alone cannot invent a competitor relation. COMPETES_WITH is mandatory.
        linked = {
            node_id
            for edge in self._edges
            if edge.type == "COMPETES_WITH"
            for node_id in (edge.source_id, edge.target_id)
        }
        result = []
        for model in sorted(self._models.values(), key=lambda node: node.id):
            profile = self._config.model_profiles.get(model.id)
            if (
                model.id not in linked
                or model.properties.brand.casefold() == "bmw"
                or profile is None
                or profile.segment != segment
                or not set(regions) & set(profile.sold_regions)
            ):
                continue
            if names and not any(name.casefold() == model.label.casefold() for name in names):
                continue
            result.append(self.get_model(model.id))
        return [record.model_copy(deep=True) for record in result]

    def get_taxonomy(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for node_id, key in sorted(self._config.feature_keys.items()):
            for domain in self._nodes[node_id].properties.domains:
                result.setdefault(domain, []).append(key)
        return {domain: sorted(set(keys)) for domain, keys in sorted(result.items())}

    def get_attribute_values(
        self, model_id: str, attributes: list[str] | None = None
    ) -> list[AttributeValue]:
        model = self._find_model(model_id)
        if model is None:
            raise KeyError(f"Unknown model: {model_id}")
        result = []
        superseded = {edge.target_id for edge in self._edges if edge.type == "SUPERSEDES"}
        for signal in sorted(self._bundle.nodes, key=lambda node: node.id):
            if not isinstance(signal, Signal) or signal.properties.capability is None:
                continue
            if signal.id in superseded:
                continue
            properties = signal.properties
            if model.id not in properties.context.vehicle_model_ids:
                continue
            feature_ids = [
                node_id
                for node_id in self._targets(signal.id, "CONCERNS")
                if isinstance(self._nodes[node_id], Feature)
            ]
            capability = properties.capability
            measurement = capability.measurement
            for feature_id in feature_ids:
                key = self._config.feature_keys.get(
                    feature_id,
                    "unmapped:" + re.sub(r"[^a-z0-9]+", "_", feature_id.lower()).strip("_"),
                )
                if attributes is not None and key not in attributes:
                    continue
                value = capability.availability
                interval = measurement.value_range if measurement else None
                if measurement is not None:
                    value = (
                        measurement.value
                        if interval is None
                        else f"{interval.minimum:g}–{interval.maximum:g}"
                    )
                notes = [
                    properties.statement,
                    f"availability={capability.availability}",
                    f"countries={properties.context.country_codes or 'unknown'}",
                    f"markets={self._regions(properties.context) or 'unknown'}",
                    *(condition.description for condition in capability.conditions),
                    *capability.notes,
                ]
                if measurement is not None:
                    notes.append(measurement_text(measurement))
                limitations = [
                    limitation
                    for ref in self._references(signal.id)
                    for limitation in self._nodes[ref.evidence_id].properties.limitations
                ]
                result.append(
                    AttributeValue(
                        node_id=signal.id,
                        attribute=key,
                        value=value,
                        value_range=interval,
                        unit=measurement.unit if measurement else None,
                        measurement=measurement,
                        availability=capability.availability,
                        epistemic_status=properties.epistemic_status,
                        context=properties.context,
                        references=self._references(signal.id),
                        limitations=list(dict.fromkeys(limitations)),
                        as_of=properties.context.as_of,
                        source_note="; ".join(notes),
                    )
                )
        return [record.model_copy(deep=True) for record in result]

    def get_feedback_items(self, filters: FeedbackFilter) -> list[FeedbackItem]:
        wanted = {
            model.id for value in filters.models if (model := self._find_model(value)) is not None
        }
        result = []
        for evidence in sorted(self._bundle.nodes, key=lambda node: node.id):
            if (
                not isinstance(evidence, Evidence)
                or evidence.properties.evidence_kind != "feedback_record"
            ):
                continue
            properties = evidence.properties
            context = properties.context
            if filters.models and not wanted & set(context.vehicle_model_ids):
                continue
            if filters.markets and not set(filters.markets) & set(context.country_codes):
                continue
            if filters.sources and properties.source_channel not in filters.sources:
                continue
            if filters.engine_types:
                engines = {value.lower().replace("beve", "bev") for value in filters.engine_types}
                if not engines & (set(context.engine_types) or {"unknown"}):
                    continue
            # These inputs do not establish a feedback date. A date filter cannot include undated rows.
            if filters.since is not None:
                continue
            classifications = []
            for classification in properties.raw_classifications:
                mapping = self._config.vfc_mappings.get(classification.vfc_combined or "")
                classifications.append(
                    FeedbackClassification(
                        feedback_type=classification.feedback_type,
                        vfc_category=classification.vfc_level2,
                        vfc_issue=classification.vfc_level3,
                        vfc_combined=classification.vfc_combined,
                        attribute=self._config.feature_keys[mapping.feature_id]
                        if mapping is not None and mapping.status == "reviewed"
                        else None,
                        mapping_status=mapping.status if mapping else None,
                        locator=classification.locator,
                    )
                )
            model_codes = [
                self._models[node_id].properties.generation_code
                for node_id in context.vehicle_model_ids
            ]
            result.append(
                FeedbackItem(
                    item_id=evidence.id,
                    text=properties.raw_text,
                    channel=properties.source_channel,
                    market=context.country_codes[0] if len(context.country_codes) == 1 else None,
                    model=model_codes[0] if len(model_codes) == 1 else None,
                    engine_type=context.engine_types[0] if len(context.engine_types) == 1 else None,
                    classifications=classifications,
                    references=self._references(evidence.id),
                    context=context,
                    limitations=properties.limitations,
                )
            )
        selected = result if filters.limit is None else result[: filters.limit]
        return [record.model_copy(deep=True) for record in selected]

    def sales_volume(
        self,
        models: list[str],
        markets: list[str] | None = None,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> list[SalesRow]:
        wanted = {model.id for value in models if (model := self._find_model(value)) is not None}
        region_filter: set[str] = set()
        for market in self._markets.values():
            if markets and (
                market.properties.code.casefold() in {value.casefold() for value in markets}
                or set(markets) & set(market.properties.country_codes)
            ):
                region_filter.add(market.properties.code)
        result = []
        for evidence in sorted(self._bundle.nodes, key=lambda node: node.id):
            if (
                not isinstance(evidence, Evidence)
                or evidence.properties.evidence_kind != "sales_statistic"
            ):
                continue
            properties = evidence.properties
            context = properties.context
            measurement = properties.measurement
            if not wanted & set(context.vehicle_model_ids):
                continue
            if measurement.period is None:
                raise ValueError(f"Sales observation {evidence.id} has no reported period")
            period = measurement.period.label
            if (period_from and period < period_from) or (period_to and period > period_to):
                continue
            regions = self._regions(context)
            if len(regions) != 1:
                raise ValueError(f"Sales observation {evidence.id} needs one original region")
            if markets and regions[0] not in region_filter:
                continue
            if (
                measurement.statistic != "count"
                or measurement.unit != "vehicles"
                or measurement.value is None
                or not measurement.value.is_integer()
                or measurement.value < 0
            ):
                raise ValueError(
                    f"Sales observation {evidence.id} is not a scalar nonnegative count"
                )
            model_codes = [
                self._models[node_id].properties.generation_code or self._models[node_id].label
                for node_id in context.vehicle_model_ids
            ]
            group = self._config.sales_groups.get(evidence.id)
            if len(model_codes) > 1 and not group:
                raise ValueError(
                    f"Combined sales observation {evidence.id} needs an explicit source group"
                )
            result.append(
                SalesRow(
                    row_id=evidence.id,
                    model=group or model_codes[0],
                    model_codes=model_codes,
                    source_group=group or model_codes[0],
                    market=regions[0],
                    period=period,
                    units=int(measurement.value),
                    status="actual"
                    if measurement.temporal_status == "historical"
                    else measurement.temporal_status,
                    measurement=measurement,
                    references=self._references(evidence.id),
                    context=context,
                    limitations=properties.limitations,
                )
            )
        return [record.model_copy(deep=True) for record in result]

    def get_study_scores(self, models: list[str], regions: list[str]) -> list[StudyScore]:
        wanted = {model.id for value in models if (model := self._find_model(value)) is not None}
        result = []
        for evidence in sorted(self._bundle.nodes, key=lambda node: node.id):
            if (
                not isinstance(evidence, Evidence)
                or evidence.properties.evidence_kind != "study_statistic"
            ):
                continue
            properties = evidence.properties
            context = properties.context
            measurement = properties.measurement
            for model_id in context.vehicle_model_ids:
                if model_id not in wanted:
                    continue
                for region in self._regions(context):
                    if region.casefold() not in {value.casefold() for value in regions}:
                        continue
                    result.append(
                        StudyScore(
                            node_id=evidence.id,
                            model=self._models[model_id].properties.generation_code or model_id,
                            region=region,
                            study=self._source(evidence).label,
                            question=measurement.question,
                            statistic=measurement.statistic,
                            response_category=measurement.response_category,
                            value=measurement.value,
                            measurement=measurement,
                            references=self._references(evidence.id),
                            context=context,
                            limitations=properties.limitations,
                        )
                    )
        return [record.model_copy(deep=True) for record in result]

    def search_documents(
        self,
        query: str,
        kinds: list[str] | None = None,
        regions: list[str] | None = None,
        k: int = 10,
    ) -> list[DocChunk]:
        if k < 0:
            raise ValueError("k must be nonnegative")
        terms = set(re.findall(r"\w+", query.casefold()))
        ranked = []
        for evidence in self._bundle.nodes:
            if not isinstance(evidence, Evidence):
                continue
            source = self._source(evidence)
            source_kind = source.properties.source_kind
            if source_kind not in {"customer_study", "industry_report", "global_indicator"}:
                continue
            kind = "study" if source_kind == "customer_study" else "report"
            if kinds and kind not in kinds:
                continue
            properties = evidence.properties
            scope = self._regions(properties.context)
            if regions and not set(regions) & set(scope):
                continue
            text = properties.raw_text or ""
            if properties.measurement is not None:
                text += "\n" + measurement_text(properties.measurement)
            text += "\nLimitations: " + "; ".join(properties.limitations)
            overlap = len(terms & set(re.findall(r"\w+", (source.label + " " + text).casefold())))
            if overlap == 0:
                continue
            publication = source.properties.publication_date
            ranked.append(
                (
                    -overlap,
                    evidence.id,
                    DocChunk(
                        node_id=evidence.id,
                        doc_title=source.label,
                        text=text,
                        url=getattr(source.properties.location, "url", None),
                        publication_label=publication,
                        published=date.fromisoformat(publication)
                        if publication and len(publication) == 10
                        else None,
                        regions=scope,
                        kind=kind,
                        measurement=properties.measurement,
                        references=self._references(evidence.id),
                        context=properties.context,
                        limitations=properties.limitations,
                    ),
                )
            )
        return [chunk.model_copy(deep=True) for _, _, chunk in sorted(ranked)[:k]]

    def resolve_citation(self, citation_id: str):
        """Resolve v1 kg:/fb: identifiers to original graph objects, without fabricated nodes."""
        node_id = citation_id
        for prefix in ("kg:", "fb:"):
            if node_id.startswith(prefix):
                node_id = node_id[len(prefix) :]
                break
        if node_id not in self._nodes:
            raise KeyError(f"Unknown citation: {citation_id}")
        return self._nodes[node_id].model_copy(deep=True)
