from copy import deepcopy
from datetime import date
from uuid import UUID

import pytest

from bmwow.agent.knowledge_bridge import configure_service, ontology, sql_client
from bmwow.agent.tools.knowledge import ModuleBackend, set_backend
from bmwow.knowledge import (
    CombinedKnowledgeService,
    FeedbackCoverage,
    FeedbackDataset,
    FeedbackFilter,
    FeedbackPage,
    FeedbackRetrieval,
    InMemoryRepository,
    VfcMapping,
    create_knowledge_service,
)
from bmwow.knowledge.feedback import feedback_id, vehicle_id
from bmwow.knowledge.ingestion import write_snapshot
from bmwow.knowledge.manifest import CurationManifest, initial_manifest
from bmwow.knowledge.neon import project_feedback
from scripts.inspect_combined_knowledge import inspect
from tests.knowledge.test_neon_feedback import aspect, parent

MODEL = "vehicle:bmw-g60"


class MemoryFeedback:
    def __init__(self):
        self.items = [
            project_feedback(
                parent(
                    id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
                    country=country,
                    derivate_code="G60",
                    feedback_explorer_id=f"invented-{country}",
                ),
                [
                    aspect(
                        id=UUID(f"00000000-0000-4000-9000-{index:012d}"),
                        aspect_term="Invented screen",
                    )
                ],
                "combined-test",
            )
            for index, country in enumerate(("DE", "GB", "US"), 1)
        ]
        self.last_filter = None
        self.coverage_calls = 0

    def dataset(self):
        return FeedbackDataset(source_id="source:combined-test", dataset_key="combined-test")

    def coverage(self):
        self.coverage_calls += 1
        return [
            FeedbackCoverage(
                derivate="G60",
                countries=sorted({item.market for item in self.items}),
                engine_types=["BEV"],
                feedback_count=len(self.items),
            )
        ]

    def read_feedback(self, filters):
        self.last_filter = filters.model_copy(deep=True)
        items = [
            item
            for item in self.items
            if (not filters.models or item.model in filters.models)
            and (not filters.markets or item.market in filters.markets)
        ]
        total = len(items)
        selected = items if filters.limit is None else items[: filters.limit]
        return FeedbackPage(
            items=deepcopy(selected),
            retrieval=FeedbackRetrieval(
                total_matching=total,
                returned_count=len(selected),
                truncated=len(selected) < total,
                selection_policy="Invented deterministic fixture selection",
            ),
        )

    def find_feedback(self, key):
        return next(
            (
                item.model_copy(deep=True)
                for item in self.items
                if item.references[0].record_key == key
            ),
            None,
        )

    def find_aspect(self, key):
        return next(
            (
                item.aspects[0].model_copy(deep=True)
                for item in self.items
                if item.aspects[0].aspect_id.endswith(":" + key)
            ),
            None,
        )


@pytest.fixture
def combined(knowledge_service):
    repo = MemoryFeedback()
    service = CombinedKnowledgeService(
        InMemoryRepository(knowledge_service.snapshot()),
        knowledge_service.config,
        repo,
        {"G60": MODEL},
    )
    return service, repo


def test_registry_merges_dataset_coverage_without_sale_inference(combined):
    service, repo = combined
    model = service.get_model("G60")
    assert model.node_id == MODEL and model.regions == ["EU", "GB", "US"]
    assert model.data_coverage["feedback_dataset"] == ["EU", "GB", "US"]
    assert model.data_coverage["sales_dataset"] == ["US"]
    assert model.sold_regions == ["US"]
    assert service.list_regions()["EU"]["markets"] == ["DE"]
    assert service.list_regions()["GB"]["markets"] == ["GB"]
    assert repo.coverage_calls == 1
    assert (
        next(row for row in service.list_supported_models() if row["model_code"] == "G60")[
            "regions"
        ]
        == model.regions
    )


def test_feedback_uses_canonical_id_and_country_scope_preserving_counts(combined):
    service, repo = combined
    page = service.get_feedback_page(FeedbackFilter(models=[MODEL], markets=["EU"], limit=1))
    assert page.retrieval.total_matching == page.retrieval.returned_count == 1
    assert "DE" in repo.last_filter.markets and "GB" not in repo.last_filter.markets
    assert repo.last_filter.models == ["G60"]
    item = page.items[0]
    assert item.context.vehicle_model_ids == [MODEL]
    assert item.context.country_codes == ["DE"] and item.context.market_ids == []
    assert item.aspects[0].context.vehicle_model_ids == [MODEL]
    assert item.item_id == feedback_id("combined-test", "invented-DE")
    assert item.date is None and item.imported_at is not None
    assert repo.items[0].context.vehicle_model_ids == [vehicle_id("G60")]
    assert (
        service.get_feedback_page(FeedbackFilter(models=["absent"])).retrieval.total_matching == 0
    )
    assert service.get_feedback_page(FeedbackFilter(models=["G68"])).items == []


@pytest.mark.parametrize("status", ["reviewed", "proposed"])
def test_sql_original_terms_only_receive_reviewed_feature_matches(knowledge_service, status):
    config = knowledge_service.config
    config.vfc_mappings["Invented screen"] = VfcMapping(
        feature_id="feature:parking-controls",
        status=status,
        rationale="Invented mapping",
    )
    service = CombinedKnowledgeService(
        InMemoryRepository(knowledge_service.snapshot()), config, MemoryFeedback(), {"G60": MODEL}
    )
    item = service.get_feedback_items(FeedbackFilter())[0]
    classification = item.classifications[0]
    assert classification.mapping_status == status
    assert classification.attribute == (
        "parking_control_usability" if status == "reviewed" else None
    )
    mapping = service.get_aspect_mapping(item.aspects[0].aspect_id)
    assert mapping == config.vfc_mappings["Invented screen"]
    mapping.rationale = "Invented local edit"
    assert service.get_aspect_mapping(item.aspects[0].aspect_id).rationale == "Invented mapping"


@pytest.mark.parametrize("accept", [False, True])
def test_proposed_term_mappings_feed_features_only_when_the_curation_opts_in(
    knowledge_service, accept
):
    config = knowledge_service.config
    config.accept_proposed_mappings = accept
    mapping = VfcMapping(
        feature_id="feature:parking-controls", status="proposed", rationale="Invented mapping"
    )
    config.vfc_mappings["Invented screen"] = mapping  # VFC labels and LLM terms map separately
    config.aspect_mappings["Invented screen"] = mapping
    service = CombinedKnowledgeService(
        InMemoryRepository(knowledge_service.snapshot()), config, MemoryFeedback(), {"G60": MODEL}
    )
    item = service.get_feedback_items(FeedbackFilter())[0]
    expected = "parking_control_usability" if accept else None
    assert item.classifications[0].attribute == expected
    assert item.aspects[0].attribute == expected
    assert item.aspects[0].mapping_status == "proposed"


def test_citation_routing_between_graph_and_sql(combined):
    service, repo = combined
    item = service.get_feedback_items(FeedbackFilter(markets=["US"]))[0]
    assert service.resolve_citation("fb:" + item.item_id) == item
    assert service.resolve_citation("kg:evidence:fixture-sales").id == "evidence:fixture-sales"
    assert service.resolve_citation("vehicle:feedback:G60").node_id == MODEL
    assert service.resolve_citation(repo.dataset().source_id) == repo.dataset()
    assert service.resolve_citation("evidence:absent") is None
    aspect = service.resolve_citation(repo.items[0].aspects[0].aspect_id)
    assert aspect.context.vehicle_model_ids == [MODEL]


def test_source_only_region_does_not_select_worldwide_feedback():
    manifest = initial_manifest()
    repo = MemoryFeedback()
    repo.items = [item for item in repo.items if item.market == "US"]
    service = CombinedKnowledgeService(
        InMemoryRepository(manifest.seed(date(2026, 10, 11), "fixture")),
        manifest.knowledge,
        repo,
        manifest.feedback_models,
    )
    assert service.list_regions()["EU"]["markets"] == ["EU"]
    page = service.get_feedback_page(
        FeedbackFilter(models=["G60"], markets=service.list_regions()["EU"]["markets"])
    )
    assert page.retrieval.total_matching == 0
    assert repo.last_filter.markets and "US" not in repo.last_filter.markets


def test_identity_mapping_must_be_explicit(knowledge_service):
    with pytest.raises(ValueError, match="unknown canonical"):
        CombinedKnowledgeService(
            InMemoryRepository(knowledge_service.snapshot()),
            knowledge_service.config,
            MemoryFeedback(),
            {"G60": "vehicle:absent"},
        )
    service = CombinedKnowledgeService(
        InMemoryRepository(knowledge_service.snapshot()),
        knowledge_service.config,
        MemoryFeedback(),
        {},
    )
    item = service.get_feedback_items(FeedbackFilter())[0]
    assert item.context.vehicle_model_ids == [] and "no reviewed canonical" in item.limitations[-1]


def test_factory_requires_sql_and_checks_private_snapshot(knowledge_service, tmp_path):
    snapshot = tmp_path / "snapshot.json"
    manifest_path = tmp_path / "config.json"
    bundle = knowledge_service.snapshot()
    write_snapshot(snapshot, bundle)
    manifest = CurationManifest(
        context_nodes=[
            node for node in bundle.nodes if node.type in {"VehicleModel", "Market", "Feature"}
        ],
        knowledge=knowledge_service.config,
        source_markets={},
        feedback_models={"G60": MODEL},
    )
    manifest_path.write_text(manifest.model_dump_json())
    with pytest.raises(ValueError, match="explicit feedback"):
        create_knowledge_service(snapshot, manifest_path)
    service = create_knowledge_service(
        snapshot, manifest_path, feedback_repository=MemoryFeedback()
    )
    assert service.sales_volume(["G68"])[0].source_group == "G60_G68"
    assert len(service.get_study_scores(["G60"], ["US"])) == 2


@pytest.mark.asyncio
async def test_existing_v1_bridge_accepts_combined_service_without_agent_changes(combined):
    service, _ = combined
    configure_service(service)
    set_backend(ModuleBackend(ontology, sql_client))
    try:
        backend = ModuleBackend(ontology, sql_client)
        assert (await backend.get_model("G60")).node_id == MODEL
        assert (
            len(await backend.get_feedback_items(FeedbackFilter(models=["G60"], markets=["EU"])))
            == 1
        )
        assert (await backend.sales_volume(["G60"], ["US"]))[0].source_group == "G60_G68"
        assert len(await backend.get_study_scores(["G60"], ["US"])) == 2
    finally:
        configure_service(None)
        set_backend(None)


@pytest.mark.asyncio
async def test_aggregate_inspection_resolves_real_interfaces_without_providers(combined):
    service, _ = combined
    result = await inspect(service, "G60", "EU")
    assert result["resolved"] and result["citations_resolved"]
    assert result["feedback_matching"] == 1
    assert result["sales_rows"] == result["study_measurements"] == 0
