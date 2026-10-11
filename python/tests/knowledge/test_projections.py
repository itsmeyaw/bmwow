from datetime import date

import pytest

from bmwow.knowledge import (
    FeedbackFilter,
    InMemoryRepository,
    KnowledgeService,
    SearchLocale,
    VfcMapping,
    create_synthetic_service,
)
from bmwow.ontology import validate_bundle
from bmwow.ontology.models import Classification, Edge, SpreadsheetLocator

MODEL = "vehicle:bmw-g60"
VARIANT = "vehicle:bmw-g60-fixture-ev"
SALES = "evidence:fixture-sales"
CUSTOMER = "evidence:fixture-customer"


def node(bundle, node_id):
    return next(node for node in bundle.nodes if node.id == node_id)


def test_complete_snapshot_validation_and_copy_isolation(bundle):
    repository = InMemoryRepository(bundle)
    bundle.nodes.clear()
    loaded = repository.load_snapshot()
    assert loaded.nodes and not validate_bundle(loaded)
    loaded.edges.clear()
    assert repository.load_snapshot().edges


@pytest.mark.parametrize("relationship", ["IN_SOURCE", "DERIVED_FROM"])
def test_missing_evidence_chain_is_rejected(bundle, relationship):
    edge = next(edge for edge in bundle.edges if edge.type == relationship)
    bundle.edges.remove(edge)
    with pytest.raises(ValueError, match="Invalid knowledge snapshot"):
        InMemoryRepository(bundle)


def test_synthetic_factory_rejects_non_synthetic_origin(bundle):
    source = next(node for node in bundle.nodes if node.type == "SourceDocument")
    source.properties.origin = "external"
    with pytest.raises(ValueError, match="wholly synthetic"):
        create_synthetic_service(bundle)


def test_registry_coverage_is_not_sale_availability(knowledge_service):
    config = knowledge_service.config
    config.model_profiles[MODEL].sold_regions = []
    service = KnowledgeService(InMemoryRepository(knowledge_service.snapshot()), config)
    model = service.get_model("G60")
    assert model.node_id == MODEL and model.regions == ["US"]
    assert "sales_dataset" in model.data_coverage
    assert model.sold_regions == []
    assert MODEL not in {model.node_id for model in service.list_portfolio(regions=["US"])}
    assert "G60" in {item["model_code"] for item in service.list_supported_models()}
    assert service.get_model("unregistered") is None
    assert service.get_model("") is None


def test_unknown_segment_cannot_be_guessed(knowledge_service):
    config = knowledge_service.config
    del config.model_profiles[MODEL]
    service = KnowledgeService(InMemoryRepository(knowledge_service.snapshot()), config)
    with pytest.raises(ValueError, match="reviewed segment profile"):
        service.get_model("G60")


def test_competitor_needs_explicit_relationship(bundle, knowledge_service):
    bundle.edges = [edge for edge in bundle.edges if edge.type != "COMPETES_WITH"]
    service = KnowledgeService(InMemoryRepository(bundle), knowledge_service.config)
    assert service.list_competitor_models("synthetic_sedan", ["US"]) == []


def test_capabilities_preserve_range_variants_and_conditions(knowledge_service):
    values = knowledge_service.get_attribute_values(VARIANT)
    charging = [value for value in values if value.attribute == "ac_charging"]
    assert {(value.value, value.availability) for value in charging} == {
        (9.0, "standard"),
        (18.0, "optional"),
    }
    for value in values:
        assert value.references and value.references[0].locator.kind == "pdf"
        assert value.context.vehicle_model_ids == [VARIANT]
        assert value.context.country_codes == ["US"]
        assert value.as_of is None  # The catalog month does not supply a day.
    interval = next(value for value in values if value.attribute == "electric_range")
    assert interval.value == "440–560" and interval.value_range.minimum == 440.0
    assert interval.value_range.maximum == 560.0
    assert interval.measurement.value is None
    assert interval.measurement.test_standard == "WLTP"
    assert "availability=optional" in next(v.source_note for v in charging if v.value == 18.0)
    assert all(
        value.context.vehicle_model_ids == [MODEL]
        for value in knowledge_service.get_attribute_values("G60")
    )


def test_attribute_view_excludes_superseded_claims_preserving_history(bundle, knowledge_service):
    old = node(bundle, "signal:fixture-range")
    current = old.model_copy(deep=True)
    current.id = "signal:fixture-range-v2"
    current.revision = 2
    current.properties.capability.measurement.value_range.minimum = 450.0
    bundle.nodes.append(current)
    for edge in list(bundle.edges):
        if edge.source_id == old.id:
            copied = edge.model_copy(deep=True)
            copied.id += "-v2"
            copied.source_id = current.id
            bundle.edges.append(copied)
    bundle.edges.append(
        Edge(
            id="edge:fixture-range-history",
            type="SUPERSEDES",
            source_id=current.id,
            target_id=old.id,
            rationale="Invented revised range claim",
            context_transfer=None,
        )
    )
    service = KnowledgeService(InMemoryRepository(bundle), knowledge_service.config)
    values = service.get_attribute_values(VARIANT, ["electric_range"])
    assert len(values) == 1 and values[0].node_id == current.id
    assert values[0].value_range.minimum == 450.0
    assert old.id in {value.id for value in service.snapshot().nodes}


def test_combined_future_sales_remain_one_original_observation(knowledge_service):
    rows = knowledge_service.sales_volume(["G60", "G68"], ["US"])
    assert len(rows) == 1
    row = rows[0]
    assert row.row_id == SALES and row.model == row.source_group == "G60_G68"
    assert row.model_codes == ["G60", "G68"] and row.units == 12400
    assert row.status == "source_reported_future" and row.period == "2030"
    assert row.references[0].evidence_id == SALES
    assert row.references[0].locator.range == "E2"
    assert knowledge_service.sales_volume(["G60"], ["US"]) == rows
    assert knowledge_service.sales_volume(["G68"], ["US"]) == rows
    assert knowledge_service.sales_volume(["G60"], ["CN"]) == []
    assert knowledge_service.sales_volume(["G60"], period_to="2029") == []


def test_zero_sales_and_explicit_country_membership(bundle, knowledge_service):
    market = node(bundle, "market:US").model_copy(deep=True)
    market.id = market.entity_key = "market:EU"
    market.label = "Invented EU grouping"
    market.properties.code = "EU"
    market.properties.country_codes = ["DE", "FR"]
    bundle.nodes.append(market)
    sales = node(bundle, SALES)
    sales.properties.context.market_ids = [market.id]
    sales.properties.context.country_codes = []
    sales.properties.measurement.value = 0.0
    signal = node(bundle, "signal:fixture-sales")
    signal.properties.context = sales.properties.context.model_copy(deep=True)
    # This test changes the source's original region; qualify its SUPPORTS edge too.
    for edge in bundle.edges:
        if edge.source_id == signal.id and edge.type == "SUPPORTS":
            edge.context_transfer = (
                "Synthetic EU observation used only as contextual support for this US need."
            )
    config = knowledge_service.config
    config.search_locales["EU"] = SearchLocale(country="de", lang="en")
    service = KnowledgeService(InMemoryRepository(bundle), config)
    assert service.sales_volume(["G60"], ["DE"])[0].market == "EU"
    assert service.sales_volume(["G60"], ["DE"])[0].units == 0
    assert service.sales_volume(["G60"], ["US"]) == []


def test_combined_sales_need_explicit_source_label(knowledge_service):
    config = knowledge_service.config
    config.sales_groups.clear()
    service = KnowledgeService(InMemoryRepository(knowledge_service.snapshot()), config)
    with pytest.raises(ValueError, match="explicit source group"):
        service.sales_volume(["G60"])


def test_mistyped_sales_units_are_not_silently_converted(bundle, knowledge_service):
    node(bundle, SALES).properties.measurement.unit = "EUR"
    service = KnowledgeService(InMemoryRepository(bundle), knowledge_service.config)
    with pytest.raises(ValueError, match="nonnegative count"):
        service.sales_volume(["G60"])


def test_config_rejects_unknown_sales_identity(knowledge_service):
    config = knowledge_service.config
    config.sales_groups["evidence:absent"] = "invented"
    with pytest.raises(ValueError, match="corresponding sales Evidence"):
        KnowledgeService(InMemoryRepository(knowledge_service.snapshot()), config)


def test_feedback_groups_all_classifications_by_original_record(bundle, knowledge_service):
    customer = node(bundle, CUSTOMER)
    customer.properties.context.engine_types = ["bev"]
    node(bundle, "signal:fixture-customer").properties.context.engine_types = ["bev"]
    for edge in bundle.edges:
        if (edge.source_id == "signal:fixture-customer" and edge.type == "SUPPORTS") or (
            edge.target_id == "signal:fixture-customer" and edge.type == "JUSTIFIED_BY"
        ):
            edge.context_transfer = "Synthetic BEV feedback used for a general usability need; engine applicability is unproven."
    customer.properties.raw_classifications = [
        Classification(
            feedback_type="complaint",
            vfc_level2="Parking",
            vfc_level3="Controls",
            vfc_combined="Parking / Controls",
            locator=SpreadsheetLocator(kind="spreadsheet", sheet="Synthetic", range="C2:E2"),
        ),
        Classification(
            feedback_type="suggestion",
            vfc_level2=None,
            vfc_level3=None,
            vfc_combined="no_class_found",
            locator=SpreadsheetLocator(kind="spreadsheet", sheet="Synthetic", range="C3:E3"),
        ),
    ]
    config = knowledge_service.config
    config.vfc_mappings["Parking / Controls"] = VfcMapping(
        feature_id="feature:parking-controls",
        status="proposed",
        rationale="Invented unreviewed mapping",
    )
    service = KnowledgeService(InMemoryRepository(bundle), config)
    items = service.get_feedback_items(FeedbackFilter(models=["G60"], markets=["US"]))
    assert len(items) == 1 and items[0].item_id == CUSTOMER
    assert items[0].engine_type == "bev" and items[0].text == customer.properties.raw_text
    assert len(items[0].classifications) == 2
    assert items[0].classifications[0].mapping_status == "proposed"
    assert items[0].classifications[0].attribute is None
    assert items[0].classifications[1].vfc_combined == "no_class_found"
    assert items[0].classifications[1].vfc_category is None
    assert items[0].classifications[1].locator.range == "C3:E3"
    config.vfc_mappings["Parking / Controls"].status = "reviewed"
    reviewed = KnowledgeService(InMemoryRepository(bundle), config)
    assert (
        reviewed.get_feedback_items(FeedbackFilter())[0].classifications[0].attribute
        == "parking_control_usability"
    )


def test_undated_feedback_and_zero_limit(knowledge_service):
    assert knowledge_service.get_feedback_items(FeedbackFilter(limit=0)) == []
    assert knowledge_service.get_feedback_items(FeedbackFilter(since=date(2020, 1, 1))) == []
    assert knowledge_service.get_feedback_items(FeedbackFilter(models=["unknown"])) == []
    item = knowledge_service.get_feedback_items(FeedbackFilter())[0]
    assert item.date is None and item.channel is None and item.rating is None


def test_study_statistics_preserve_unknowns_and_response_categories(knowledge_service):
    scores = knowledge_service.get_study_scores(["G60"], ["US"])
    assert len(scores) == 2
    mean = next(score for score in scores if score.statistic == "mean")
    share = next(score for score in scores if score.statistic == "proportion")
    assert mean.value == 6.4 and mean.measurement.unit == "unknown_rating_scale"
    assert mean.measurement.scale is None and mean.measurement.sample_size is None
    assert share.value == 0.28 and share.response_category == "Difficult to use"
    assert share.measurement.denominator is None and share.measurement.sample_size is None
    assert mean.question and mean.references[0].locator.range == "B2"
    assert knowledge_service.get_study_scores(["G60"], ["EU"]) == []


def test_document_search_keeps_original_measurements_and_partial_date(knowledge_service):
    chunks = knowledge_service.search_documents("parking", ["study"], ["US"])
    assert {chunk.node_id for chunk in chunks} == {
        "evidence:fixture-study-mean",
        "evidence:fixture-study-share",
    }
    assert all(chunk.publication_label == "2026-09" and chunk.published is None for chunk in chunks)
    assert all(chunk.references and "sample_size=None" in chunk.text for chunk in chunks)
    assert knowledge_service.search_documents("parking", regions=["EU"]) == []
    assert knowledge_service.search_documents("no_matching_terms") == []
    assert knowledge_service.search_documents("parking", k=0) == []
    with pytest.raises(ValueError, match="nonnegative"):
        knowledge_service.search_documents("parking", k=-1)


def test_public_projections_and_config_are_detached(knowledge_service):
    original = knowledge_service.snapshot().model_dump(mode="json")
    knowledge_service.get_attribute_values(VARIANT)[0].context.country_codes.clear()
    knowledge_service.get_feedback_items(FeedbackFilter())[0].references[0].locator.range = "Z999"
    knowledge_service.sales_volume(["G60"])[0].measurement.value = 1.0
    knowledge_service.get_study_scores(["G60"], ["US"])[0].measurement.value = 1.0
    knowledge_service.search_documents("parking")[0].context.vehicle_model_ids.clear()
    knowledge_service.config.model_profiles[MODEL].sold_regions.clear()
    assert knowledge_service.snapshot().model_dump(mode="json") == original
    assert knowledge_service.get_model("G60").sold_regions == ["US"]
