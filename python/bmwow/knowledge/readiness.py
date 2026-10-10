"""Aggregate, provider-free readiness at the data-to-agent boundary."""

from collections import Counter

from pydantic import Field

from bmwow.ontology import snapshot_fingerprint, validate_bundle

from .combined import CombinedKnowledgeService
from .config import Configuration
from .records import FeedbackFilter


class DataReadiness(Configuration):
    model: str
    region: str
    feature_keys: list[str]
    graph_valid: bool
    snapshot_fingerprint: str
    segment_reviewed: bool
    feedback_matching: int
    feedback_selected: int
    feedback_truncated: bool
    feedback_versioned: int
    feedback_distinct_texts: int
    feedback_with_reviewed_aspects: int
    feedback_with_theme_aspects: int
    aspect_counts: dict[str, int]
    mapping_counts: dict[str, int]
    quote_counts: dict[str, int]
    rejected_inferred_aspects: int
    usable_theme_aspects: int
    source_versions: int
    sales_region: str
    sales_rows: int
    sales_zeros: int
    sales_combined_rows: int
    sales_future_rows: int
    study_region: str
    study_measurements: int
    study_reviewed_measurements: int
    study_theme_measurements: int
    study_unknown_sample_size: int
    study_unknown_scale: int
    study_unknown_population: int
    catalog_claims: int
    catalog_theme_claims: int
    catalog_theme_claims_in_region: int
    citations_checked: int
    citations_unresolved: int
    missing_datasets: list[str]
    limitations: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    ready_for_agents: bool


def inspect_readiness(
    service: CombinedKnowledgeService,
    *,
    model: str,
    region: str,
    feature_keys: list[str],
    limit: int = 200,
    sales_region: str | None = None,
    study_region: str | None = None,
) -> DataReadiness:
    selected_model = service.get_model(model)
    if selected_model is None:
        raise ValueError("Selected model has no configured canonical identity")
    snapshot, config = service.snapshot(), service.config
    page = service.get_feedback_page(FeedbackFilter(models=[model], markets=[region], limit=limit))
    sales_region, study_region = sales_region or region, study_region or region
    sales = service.sales_volume([model], [sales_region])
    studies = service.get_study_scores([model], [study_region])
    capabilities = service.get_attribute_values(selected_model.node_id)
    catalog = [value for value in capabilities if value.availability is not None]
    theme_catalog = [value for value in catalog if value.attribute in feature_keys]
    theme_scope = [
        value
        for value in theme_catalog
        if value.context
        and (region in value.context.country_codes or region in value.context.market_ids)
    ]
    aspects = [aspect for item in page.items for aspect in item.aspects]
    mappings = Counter(aspect.mapping_status or "unmapped" for aspect in aspects)
    quote_counts = Counter(aspect.quote_status for aspect in aspects)
    usable_theme = [
        aspect
        for aspect in aspects
        if aspect.attribute in feature_keys
        and (aspect.extraction_source == "vfc_label" or aspect.quote_status == "supported")
    ]
    source_versions = {
        origin.source_hash
        for item in page.items
        if item.provenance
        for origin in item.provenance.origins
    }
    reviewed_studies = [
        score
        for score in studies
        if (mapping := config.study_mappings.get(score.question or ""))
        and mapping.status == "reviewed"
    ]
    theme_studies = [
        score
        for score in reviewed_studies
        if config.feature_keys[config.study_mappings[score.question].feature_id] in feature_keys
    ]
    references = [
        ref
        for item in [*page.items, *aspects, *sales, *studies, *catalog]
        for ref in item.references
    ]
    citations = {ref.evidence_id for ref in references}
    unresolved = sum(service.resolve_citation(citation) is None for citation in citations)
    missing = [
        kind
        for kind, present in (
            ("feedback", bool(page.items)),
            ("sales", bool(sales)),
            ("studies", bool(studies)),
            ("catalog", bool(catalog)),
        )
        if not present
    ]
    blockers = [f"Missing selected-scope dataset: {kind}" for kind in missing]
    if selected_model.segment == "unknown":
        blockers.append("Model segment awaits human curation")
    if not feature_keys or set(feature_keys) - set(config.feature_keys.values()):
        blockers.append("Theme Features await curation")
    if not usable_theme:
        blockers.append("No reviewed feedback mapping for the selected theme")
    if not theme_studies:
        blockers.append("No reviewed study mapping for the selected theme")
    if not theme_scope:
        blockers.append("No reviewed catalog theme claim establishes the selected region")
    if sum(bool(item.provenance) for item in page.items) != len(page.items):
        blockers.append("Selected feedback includes imports without version provenance")
    if unresolved:
        blockers.append("Selected evidence includes unresolved citations")
    graph_valid = not validate_bundle(snapshot)
    if not graph_valid:
        blockers.append("Complete snapshot fails ontology validation")
    limitations = list(page.retrieval.limitations)
    limitations.extend(
        [
            "Coverage denominators refer to selected feedback and aspects; they do not measure reviewer accuracy.",
            "Feedback event dates, source population, and study sample/scale metadata remain unknown unless reported.",
            "Distinct feedback identities are retained even when their text is identical; text duplication is not cluster noise.",
            "Sales and studies use explicit source-region selectors; Europe totals are not expanded to feedback countries.",
        ]
    )
    if theme_catalog and len(theme_scope) != len(theme_catalog):
        limitations.append(
            "Catalog evidence from another region is available only with its original scope qualification."
        )
    return DataReadiness(
        model=model,
        region=region,
        feature_keys=feature_keys,
        graph_valid=graph_valid,
        snapshot_fingerprint=snapshot_fingerprint(snapshot),
        segment_reviewed=selected_model.segment != "unknown",
        feedback_matching=page.retrieval.total_matching,
        feedback_selected=len(page.items),
        feedback_truncated=page.retrieval.truncated,
        feedback_versioned=sum(bool(i.provenance) for i in page.items),
        feedback_distinct_texts=len({i.text for i in page.items}),
        feedback_with_reviewed_aspects=sum(
            any(a.mapping_status == "reviewed" for a in i.aspects) for i in page.items
        ),
        feedback_with_theme_aspects=sum(
            any(a.attribute in feature_keys for a in i.aspects) for i in page.items
        ),
        aspect_counts=dict(Counter(a.extraction_source for a in aspects)),
        mapping_counts=dict(mappings),
        quote_counts=dict(quote_counts),
        rejected_inferred_aspects=sum(
            a.extraction_source == "llm" and a.quote_status in {"missing", "mismatch"}
            for a in aspects
        ),
        usable_theme_aspects=len(usable_theme),
        source_versions=len(source_versions),
        sales_region=sales_region,
        sales_rows=len(sales),
        sales_zeros=sum(s.units == 0 for s in sales),
        sales_combined_rows=sum(len(s.model_codes) > 1 for s in sales),
        sales_future_rows=sum(s.status == "source_reported_future" for s in sales),
        study_region=study_region,
        study_measurements=len(studies),
        study_reviewed_measurements=len(reviewed_studies),
        study_theme_measurements=len(theme_studies),
        study_unknown_sample_size=sum(s.measurement.sample_size is None for s in studies),
        study_unknown_scale=sum(s.measurement.scale is None for s in studies),
        study_unknown_population=sum(s.measurement.population is None for s in studies),
        catalog_claims=len(catalog),
        catalog_theme_claims=len(theme_catalog),
        catalog_theme_claims_in_region=len(theme_scope),
        citations_checked=len(citations),
        citations_unresolved=unresolved,
        missing_datasets=missing,
        limitations=limitations,
        blockers=blockers,
        ready_for_agents=not blockers,
    )
