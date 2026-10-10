from datetime import date

from bmwow.knowledge import CombinedKnowledgeService, FeedbackFilter, InMemoryRepository, VfcMapping
from bmwow.knowledge.catalog import prepare_catalog, stage_catalog
from bmwow.knowledge.ingestion import merge_candidate
from bmwow.knowledge.neon import project_feedback
from bmwow.knowledge.readiness import inspect_readiness
from tests.knowledge.test_catalog import make_manifest, reviewed, synthetic_pdf
from tests.knowledge.test_combined import MemoryFeedback
from tests.knowledge.test_feedback_history import metadata
from tests.knowledge.test_neon_feedback import aspect, parent
from tests.knowledge.test_workbooks import imported, make_inputs


def test_readiness_keeps_denominators_scope_and_pending_mapping_visible(knowledge_service):
    config = knowledge_service.config
    config.vfc_mappings["Invented screen"] = VfcMapping(
        feature_id="feature:parking-controls",
        status="proposed",
        rationale="Invented pending semantic review",
    )
    service = CombinedKnowledgeService(
        InMemoryRepository(knowledge_service.snapshot()),
        config,
        MemoryFeedback(),
        {"G60": "vehicle:bmw-g60"},
    )
    report = inspect_readiness(
        service,
        model="G60",
        region="EU",
        feature_keys=["parking_control_usability"],
        sales_region="US",
        study_region="US",
        limit=1,
    )
    assert report.graph_valid and report.citations_unresolved == 0
    assert report.feedback_matching == report.feedback_selected == 1
    assert report.mapping_counts == {"proposed": 1}
    assert report.feedback_with_reviewed_aspects == 0
    assert report.sales_region == "US" and report.study_region == "US"
    assert report.catalog_theme_claims_in_region == 0
    assert not report.ready_for_agents


def test_reviewed_aspects_carry_feature_ids_without_rewriting_original_labels(knowledge_service):
    config = knowledge_service.config
    config.vfc_mappings["Invented screen"] = VfcMapping(
        feature_id="feature:parking-controls",
        status="reviewed",
        rationale="Invented approved mapping",
    )
    service = CombinedKnowledgeService(
        InMemoryRepository(knowledge_service.snapshot()),
        config,
        MemoryFeedback(),
        {"G60": "vehicle:bmw-g60"},
    )
    report = inspect_readiness(
        service, model="G60", region="US", feature_keys=["parking_control_usability"]
    )
    assert report.mapping_counts == {"reviewed": 1}
    assert report.feedback_with_theme_aspects == 1
    item = service.get_feedback_items(FeedbackFilter())[0]
    aspect = item.aspects[0]
    assert aspect.aspect_term == "Invented screen"
    assert (
        aspect.feature_id == "feature:parking-controls"
        and aspect.attribute == "parking_control_usability"
    )
    assert service.resolve_citation(aspect.aspect_id).attribute == aspect.attribute


def test_raw_workbooks_catalog_and_versioned_feedback_reach_ready_boundary(tmp_path):
    workbook_inputs = make_inputs(tmp_path)
    manifest = make_manifest()
    path = tmp_path / "invented.pdf"
    synthetic_pdf(path)
    catalog_review = prepare_catalog(path)
    manifest.knowledge.model_profiles["vehicle:bmw-g60"].segment = "Invented synthetic segment"
    mapping = VfcMapping(
        feature_id="feature:invented-seat",
        status="reviewed",
        rationale="Synthetic reviewed mapping",
    )
    manifest.knowledge.vfc_mappings["Invented screen"] = mapping
    manifest.knowledge.study_mappings["Invented usability question"] = mapping
    bundle, config, _ = imported(workbook_inputs, manifest)
    review = reviewed(catalog_review)
    review.model_id = "vehicle:bmw-g60"
    review.country_codes = ["US"]
    review.edition_note = "Invented synthetic US edition"
    bundle = merge_candidate(
        bundle, stage_catalog(review, manifest, as_of=date(2026, 10, 11), origin="synthetic")
    )
    feedback = MemoryFeedback()
    feedback.items = [
        project_feedback(
            parent(derivate_code="G60", provenance=metadata()), [aspect()], "combined-test"
        )
    ]

    # The fixture emulates archive retrieval; the SQL adapter's history transport is tested separately.
    class ArchivedFeedback(MemoryFeedback):
        def find_revision(self, revision):
            return (
                self.items[0].model_copy(deep=True)
                if revision == metadata()["revision_id"]
                else None
            )

    archive = ArchivedFeedback()
    archive.items = feedback.items
    service = CombinedKnowledgeService(
        InMemoryRepository(bundle), config, archive, manifest.feedback_models
    )
    report = inspect_readiness(service, model="G60", region="US", feature_keys=["invented_seat"])
    assert report.ready_for_agents and report.blockers == []
    assert report.feedback_versioned == report.feedback_with_theme_aspects == 1
    assert report.study_theme_measurements == 2 and report.sales_rows == 3
    assert report.catalog_theme_claims_in_region == 1 and report.citations_unresolved == 0
    assert report.study_unknown_sample_size == 2


def test_invalid_inferred_quote_cannot_satisfy_theme_readiness(knowledge_service):
    config = knowledge_service.config
    config.aspect_mappings["Invented screen"] = VfcMapping(
        feature_id="feature:parking-controls",
        status="reviewed",
        rationale="Invented semantic mapping; quote still needs verification",
    )
    feedback = MemoryFeedback()
    feedback.items = [
        project_feedback(
            parent(derivate_code="G60"),
            [aspect(extraction_source="llm", quote_snippet="Fabricated invented quotation")],
            "combined-test",
        )
    ]
    service = CombinedKnowledgeService(
        InMemoryRepository(knowledge_service.snapshot()),
        config,
        feedback,
        {"G60": "vehicle:bmw-g60"},
    )
    report = inspect_readiness(
        service, model="G60", region="US", feature_keys=["parking_control_usability"]
    )
    assert report.mapping_counts == {"reviewed": 1}
    assert report.rejected_inferred_aspects == 1 and report.usable_theme_aspects == 0
    assert "No reviewed feedback mapping for the selected theme" in report.blockers
