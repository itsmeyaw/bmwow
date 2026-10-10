"""Synthetic tests: nothing from the live BMW database is stored in this file."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest

from bmwow.agent.knowledge_bridge import configure_service, ontology, sql_client
from bmwow.agent.models.evidence import AnalysisRequest, Source
from bmwow.agent.nodes import feedback
from bmwow.agent.nodes.common import AgentContext
from bmwow.agent.registry import load_registry
from bmwow.agent.resolve import resolve_request
from bmwow.agent.rules import load_rules
from bmwow.agent.sources import feedback_source
from bmwow.agent.taxonomy import load_taxonomy
from bmwow.agent.tools.knowledge import ModuleBackend, set_backend
from bmwow.knowledge import (
    FeedbackCoverage,
    FeedbackFilter,
    FeedbackKnowledgeService,
    FeedbackServiceConfig,
    KnowledgeUnavailableError,
    ModelProfile,
    create_synthetic_service,
)
from bmwow.knowledge.feedback import feedback_id
from bmwow.knowledge.neon import (
    FeedbackStorageError,
    NeonFeedbackConfig,
    NeonFeedbackRepository,
    create_neon_feedback_service,
    project_feedback,
)
from bmwow.ontology.models import Evidence
from scripts.inspect_neon_feedback import inspect_service

PARENT_ID = UUID("00000000-0000-4000-8000-000000000001")
ASPECT_ID = UUID("00000000-0000-4000-8000-000000000010")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
VERBATIM = "  Invented text: the screen freezes, but the seats are superb. Ω  "


def parent(**changes):
    return {
        "id": PARENT_ID,
        "feedback_explorer_id": "synthetic feedback/one",
        "source": "Source A",
        "brand": "Invented Brand",
        "sales_description": "Invented vehicle",
        "country": "US",
        "derivate_code": "G70",
        "engine_type": "BEV",
        "raw_feedback": VERBATIM,
        "created_at": NOW,
        **changes,
    }


def aspect(**changes):
    return {
        "id": ASPECT_ID,
        "feedback_entry_id": PARENT_ID,
        "feedback_type": "Defect",
        "vfc_category": "Infotainment & Connectivity",
        "aspect_term": "Invented screen",
        "aspect_label_raw": "Invented freezing label",
        "issue_type": "Malfunction",
        "quote_snippet": None,
        "sentiment": "Negative",
        "sentiment_score": Decimal("-0.75"),
        "extraction_source": "vfc_label",
        "created_at": NOW,
        **changes,
    }


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return deepcopy(self.rows)

    def fetchone(self):
        return deepcopy(self.rows[0])


class Connection:
    """Scripted transport; tests separately assert SQL selection/parameterization boundaries."""

    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []
        self.read_only = None
        self.isolation_level = None
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def execute(self, query, params=()):
        self.calls.append((query, params))
        assert self.read_only is True
        assert self.isolation_level == psycopg.IsolationLevel.REPEATABLE_READ
        if "set_config" in query:
            return Result([])
        return Result(self.responses.popleft())


def repository(*responses, config=None):
    conn = Connection(*responses)
    kwargs_seen = {}

    def connect(dsn, **kwargs):
        assert dsn == "postgresql://synthetic-only"
        kwargs_seen.update(kwargs)
        return conn

    repo = NeonFeedbackRepository("postgresql://synthetic-only", config, connect=connect)
    return repo, conn, kwargs_seen


def test_transient_connection_failure_is_retried_before_transaction_only():
    conn = Connection([])
    calls = []

    def connect(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise psycopg.OperationalError("Invented network timeout")
        return conn

    repo = NeonFeedbackRepository(
        "postgresql://synthetic-only",
        NeonFeedbackConfig(connection_retry_delay_seconds=0),
        connect=connect,
    )
    assert repo.coverage() == []
    assert len(calls) == 2 and conn.closed


def test_authentication_failure_is_not_retried():
    calls = []

    def connect(*args, **kwargs):
        calls.append(True)
        raise psycopg.errors.InvalidPassword("Invented private credentials")

    repo = NeonFeedbackRepository("postgresql://synthetic-only", connect=connect)
    with pytest.raises(FeedbackStorageError, match="connectivity"):
        repo.coverage()
    assert len(calls) == 1


def test_query_failure_is_not_replayed():
    conn = Connection()
    calls = []

    def connect(*args, **kwargs):
        calls.append(True)
        return conn

    def execute(*args, **kwargs):
        raise psycopg.OperationalError("Invented failure after connecting")

    conn.execute = execute
    repo = NeonFeedbackRepository("postgresql://synthetic-only", connect=connect)
    with pytest.raises(FeedbackStorageError):
        repo.coverage()
    assert len(calls) == 1


def test_projection_preserves_verbatim_original_labels_and_distinct_aspects():
    inferred = aspect(
        id=UUID("00000000-0000-4000-8000-000000000011"),
        extraction_source="llm",
        quote_snippet="the seats are superb",
        aspect_label_raw=None,
        issue_type="Praise",
        sentiment="Positive",
        sentiment_score=Decimal("0.9"),
    )
    item = project_feedback(parent(), [aspect(), inferred], "synthetic-feedback")
    assert item.text == VERBATIM and item.date is None and item.rating is None
    assert item.imported_at == NOW and item.context.as_of is None
    assert item.engine_type == "BEV" and item.context.engine_types == ["bev"]
    assert len(item.aspects) == 2 and len(item.classifications) == 1
    curated = item.aspects[0]
    assert curated.aspect_term == "Invented screen"
    assert curated.vfc_category == "Infotainment & Connectivity"
    assert curated.quote_status == "not_applicable" and curated.sentiment_score == -0.75
    assert item.classifications[0].vfc_category == curated.aspect_term
    assert item.classifications[0].vfc_combined is None
    assert item.classifications[0].attribute is None
    assert item.aspects[1].quote_status == "supported"
    assert item.aspects[1].quote == "the seats are superb"
    assert item.references[0].record_key == "synthetic feedback/one"
    assert item.references[0].locator.record_key == str(PARENT_ID)
    assert curated.locator.table == "public.feedback_aspects"
    assert curated.locator.original_locator is None
    assert curated.references == item.references
    assert curated.references[0].record_key == item.references[0].record_key
    assert item.item_id == "evidence:synthetic-feedback:synthetic%20feedback%2Fone"


@pytest.mark.parametrize(
    ("quote", "status"), [(None, "missing"), ("   ", "missing"), ("fabricated words", "mismatch")]
)
def test_unsupported_inference_remains_visible_with_qualification(quote, status):
    item = project_feedback(
        parent(), [aspect(extraction_source="llm", quote_snippet=quote)], "synthetic"
    )
    assert not item.classifications and len(item.aspects) == 1
    assert item.aspects[0].quote == quote and item.aspects[0].quote_status == status
    assert item.aspects[0].limitations


def test_zero_aspects_null_engine_and_neutral_score_do_not_create_information():
    item = project_feedback(parent(engine_type=None), [], "synthetic")
    assert item.aspects == item.classifications == []
    assert item.engine_type is None and item.context.engine_types == ["unknown"]
    item = project_feedback(
        parent(),
        [aspect(issue_type="Feature Request", sentiment="Neutral", sentiment_score=Decimal("0"))],
        "synthetic",
    )
    assert item.aspects[0].sentiment_score == 0
    assert "intensity" not in item.aspects[0].model_dump()


def test_parent_limit_precedes_aspects_and_count_is_not_join_inflated():
    parents = [parent(), parent(id=UUID(int=2), feedback_explorer_id="synthetic-two")]
    repo, conn, kwargs = repository([{"n": 5}], parents, [aspect(), aspect(id=UUID(int=11))])
    page = repo.read_feedback(FeedbackFilter(models=["g70"], markets=["us"], limit=2))
    assert len(page.items) == 2 and len(page.items[0].aspects) == 2
    assert page.items[1].aspects == []
    assert (
        page.items[0].text == page.items[1].text
    )  # Independent identical Verbatim stays distinct.
    assert page.retrieval.total_matching == 5 and page.retrieval.returned_count == 2
    assert page.retrieval.truncated and all(item.retrieval == page.retrieval for item in page.items)
    queries = [query for query, _ in conn.calls]
    assert "JOIN" not in queries[1] and "LIMIT %s" in queries[2]
    assert 'COLLATE "C"' in queries[2] and "feedback_aspects" not in queries[2]
    assert conn.calls[2][1] == [["G70"], ["US"], 2]
    assert conn.calls[3][1] == ([str(PARENT_ID), str(UUID(int=2))],)
    assert conn.closed and not conn.responses
    assert kwargs["prepare_threshold"] is None and kwargs["connect_timeout"] == 10


def test_filter_parameters_are_never_interpolated_into_sql():
    hostile = "US'); DROP TABLE feedback_entries; --"
    repo, conn, _ = repository([{"n": 0}], [])
    repo.read_feedback(
        FeedbackFilter(
            models=["g70"], markets=[hostile], engine_types=["BEV", "unknown"], sources=["Source A"]
        )
    )
    query, params = conn.calls[1]
    assert hostile.upper() not in query and hostile.upper() in params[1]
    assert params == [["G70"], [hostile.upper()], ["Source A"], ["BEV"]]
    assert "engine_type IS NULL" in query


def test_eu_alias_expands_before_count_and_limit_without_replacing_original_countries():
    parents = [
        parent(country="DE"),
        parent(id=UUID(int=2), feedback_explorer_id="synthetic-fr", country="FR"),
    ]
    repo, conn, _ = repository([{"n": 2}], parents, [])
    page = repo.read_feedback(
        FeedbackFilter(models=["G70"], markets=[" eu ", "DE", "US", "eu"], limit=2)
    )
    countries = conn.calls[1][1][1]
    assert len(countries) == len(set(countries)) == 28
    assert {"DE", "FR", "IE", "CY", "US"} <= set(countries)
    assert not {"EU", "GB", "NO", "CH"} & set(countries)
    assert "country = ANY(%s)" in conn.calls[1][0]
    assert conn.calls[1][1] == conn.calls[2][1][:-1]
    assert [item.market for item in page.items] == ["DE", "FR"]
    assert [item.context.country_codes for item in page.items] == [["DE"], ["FR"]]
    assert page.retrieval.returned_count == page.retrieval.total_matching == 2


@pytest.mark.parametrize("limit", [None, 10000])
def test_default_and_hard_limit_are_explicit(limit):
    repo, conn, _ = repository([{"n": 1}], [parent()], [])
    page = repo.read_feedback(FeedbackFilter(limit=limit))
    assert conn.calls[2][1][-1] == (200 if limit is None else 5000)
    if limit:
        assert any("capped" in note for note in page.retrieval.limitations)


def test_zero_limit_preserves_count_and_since_excludes_undated_feedback():
    repo, conn, _ = repository([{"n": 3}], [])
    page = repo.read_feedback(FeedbackFilter(limit=0))
    assert page.items == [] and page.retrieval.total_matching == 3 and page.retrieval.truncated
    assert len(conn.calls) == 3
    repo, conn, _ = repository([{"n": 0}], [])
    page = repo.read_feedback(FeedbackFilter(since=date(2020, 1, 1)))
    assert "FALSE" in conn.calls[1][0] and "created_at" not in conn.calls[1][0]
    assert page.retrieval.limitations and not page.items


def test_database_errors_are_sanitized_and_never_fall_back():
    def failing_connect(*args, **kwargs):
        raise psycopg.OperationalError("synthetic-password synthetic-feedback-text")

    repo = NeonFeedbackRepository("postgresql://synthetic-secret", connect=failing_connect)
    with pytest.raises(FeedbackStorageError) as caught:
        repo.read_feedback(FeedbackFilter())
    assert "synthetic-password" not in str(caught.value)
    assert "synthetic-feedback-text" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_invalid_imported_data_is_reported_without_verbatim():
    repo, _, _ = repository([{"n": 1}], [parent()], [aspect(sentiment="invalid")])
    with pytest.raises(FeedbackStorageError, match="does not match") as caught:
        repo.read_feedback(FeedbackFilter())
    assert VERBATIM not in str(caught.value)


def test_configuration_is_local_explicit_and_does_not_connect(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_neon_feedback_service()
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic-only")
    service = create_neon_feedback_service()
    assert isinstance(service, FeedbackKnowledgeService)
    assert "synthetic-only" not in repr(service)
    with pytest.raises(ValueError, match="default_limit"):
        NeonFeedbackRepository("synthetic", NeonFeedbackConfig(default_limit=10, max_limit=2))
    repository_config = NeonFeedbackConfig(dataset_key="synthetic-config")
    repo = NeonFeedbackRepository("synthetic", repository_config)
    repository_config.dataset_key = "changed"
    repo.config.dataset_key = "another-change"
    assert repo.dataset().dataset_key == "synthetic-config"


def test_snapshot_feedback_honors_additive_source_and_engine_filters(bundle):
    original = next(
        node
        for node in bundle.nodes
        if isinstance(node, Evidence) and node.properties.evidence_kind == "feedback_record"
    )
    original.properties.source_channel = "Synthetic A"
    knowledge_service = create_synthetic_service(bundle)
    item = knowledge_service.get_feedback_items(FeedbackFilter())[0]
    assert knowledge_service.get_feedback_items(FeedbackFilter(sources=["Synthetic A"]))
    assert not knowledge_service.get_feedback_items(FeedbackFilter(sources=["absent-source"]))
    engine = "BEVE" if item.engine_type == "bev" else item.engine_type or "unknown"
    selected = knowledge_service.get_feedback_items(FeedbackFilter(engine_types=[engine]))
    assert item.item_id in {value.item_id for value in selected}
    opposite = "ICE" if item.engine_type == "phev" else "PHEV"
    selected = knowledge_service.get_feedback_items(FeedbackFilter(engine_types=[opposite]))
    assert item.item_id not in {value.item_id for value in selected}


class MemoryFeedbackRepository:
    """Synthetic query-port stand-in; uses the tested SQL projection, never real feedback."""

    def __init__(self):
        repo, _, _ = repository([{"n": 1}], [parent()], [aspect()])
        self.page = repo.read_feedback(FeedbackFilter(models=["G70"], markets=["US"]))
        self.metadata = repo.dataset()

    def read_feedback(self, filters):
        return self.page.model_copy(deep=True)

    def coverage(self):
        from bmwow.knowledge import FeedbackCoverage

        return [
            FeedbackCoverage(
                derivate="G70",
                countries=["US"],
                engine_types=["BEV"],
                feedback_count=1,
                brand="Invented Brand",
            )
        ]

    def dataset(self):
        return self.metadata.model_copy(deep=True)

    def find_feedback(self, key):
        item = self.page.items[0]
        return item.model_copy(deep=True) if key == item.references[0].record_key else None

    def find_aspect(self, key):
        value = self.page.items[0].aspects[0]
        return value.model_copy(deep=True) if key == str(ASPECT_ID) else None


async def test_eu_and_us_request_expands_registry_and_retains_country_scoped_sources(monkeypatch):
    parents = [
        parent(country="DE"),
        parent(id=UUID(int=2), feedback_explorer_id="synthetic-fr", country="FR"),
        parent(id=UUID(int=3), feedback_explorer_id="synthetic-us", country="US"),
    ]
    repo, conn, _ = repository(
        [{"n": 3}], parents, [aspect(), aspect(id=UUID(int=11), feedback_entry_id=UUID(int=2))]
    )
    monkeypatch.setattr(
        repo,
        "coverage",
        lambda: [
            FeedbackCoverage(
                derivate="G70",
                countries=["DE", "FR", "US", "GB", "NO"],
                engine_types=["BEV"],
                feedback_count=5,
            ),
            FeedbackCoverage(
                derivate="G60", countries=["JP"], engine_types=["ICE"], feedback_count=1
            ),
        ],
    )
    service = FeedbackKnowledgeService(repo)
    bridge = ModuleBackend(ontology, sql_client)
    configure_service(service)
    set_backend(bridge)
    try:
        registry = await load_registry()
        assert set(registry.regions) == {"EU", "GB", "JP", "NO", "US"}
        assert registry.regions["EU"].markets == ["DE", "FR"]
        assert registry.regions["EU"].search.country == "de"
        assert registry.models["G70"].regions == ["EU", "GB", "NO", "US"]
        assert registry.check(AnalysisRequest(model_code="G70"))[1] == ["EU", "GB", "NO", "US"]
        with pytest.raises(ValueError, match="no data for region"):
            registry.check(AnalysisRequest(model_code="G60", regions=["EU"]))
        brief = await resolve_request(AnalysisRequest(model_code="G70", regions=["eu", "US"]))
        assert brief.regions == ["EU", "US"] and brief.markets == ["DE", "FR", "US"]
        assert brief.region_markets == {"EU": ["DE", "FR"], "US": ["US"]}
        assert brief.region_of("DE") == brief.region_of("FR") == "EU"
        assert brief.region_of("US") == "US" and brief.region_of("GB") is None
        assert brief.reference_model.data_coverage == {"feedback_dataset": ["EU", "GB", "NO", "US"]}
        assert not brief.reference_model.sold_regions
        page = await bridge.get_feedback_page(
            FeedbackFilter(models=[brief.model_code], markets=brief.markets, limit=3)
        )
        assert conn.calls[1][1] == [["G70"], ["DE", "FR", "US"]]
        assert page.retrieval.total_matching == page.retrieval.returned_count == 3
        assert [item.market for item in page.items] == ["DE", "FR", "US"]
        assert sum(len(item.aspects) for item in page.items) == 2
        for item in page.items:
            source = Source.model_validate_json(feedback_source(item).model_dump_json())
            assert source.context.country_codes == [item.market]
            assert all(value.context.country_codes == [item.market] for value in source.aspects)
            assert source.references == item.references
    finally:
        configure_service(None)
        set_backend(None)


@pytest.mark.parametrize("country", ["CY", "IE", "LT", "PT"])
def test_eu_coverage_uses_imported_members_and_a_real_country_search_locale(monkeypatch, country):
    repo = MemoryFeedbackRepository()
    monkeypatch.setattr(
        repo,
        "coverage",
        lambda: [
            FeedbackCoverage(
                derivate="G70", countries=[country], engine_types=["BEV"], feedback_count=1
            )
        ],
    )
    service = FeedbackKnowledgeService(repo)
    assert service.list_regions() == {
        "EU": {"markets": [country], "search": {"country": country.lower(), "lang": "en"}}
    }
    assert (
        service.list_supported_models()[0]["regions"] == service.get_model("G70").regions == ["EU"]
    )


def test_no_eu_country_coverage_does_not_create_an_eu_region():
    service = FeedbackKnowledgeService(MemoryFeedbackRepository())
    assert "EU" not in service.list_regions()
    assert service.get_model("G70").regions == ["US"]


@pytest.mark.parametrize("selector", ["EU", "DE"])
async def test_inspection_accepts_eu_and_individual_member_country_selectors(monkeypatch, selector):
    repo = MemoryFeedbackRepository()
    repo.page.items = [project_feedback(parent(country="DE"), [aspect()], "bmw-feedback")]
    monkeypatch.setattr(
        repo,
        "coverage",
        lambda: [
            FeedbackCoverage(
                derivate="G70", countries=["DE"], engine_types=["BEV"], feedback_count=1
            )
        ],
    )
    result = await inspect_service(
        FeedbackKnowledgeService(repo), derivate="G70", country=selector, limit=50
    )
    assert result["request_has_feedback_coverage"] is True
    assert result["citation_checks_passed"] == 2
    assert result["country"] == selector


@pytest.fixture
def feedback_bridge():
    repo = MemoryFeedbackRepository()
    service = FeedbackKnowledgeService(repo)
    configure_service(service)
    bridge = ModuleBackend(ontology, sql_client)
    set_backend(bridge)
    yield service, bridge
    configure_service(None)
    set_backend(None)


async def test_v1_sources_round_trip_aspects_scope_counts_and_import_time(feedback_bridge):
    service, bridge = feedback_bridge
    item = (await bridge.get_feedback_items(FeedbackFilter()))[0]
    source = Source.model_validate_json(feedback_source(item).model_dump_json())
    assert source.aspects == item.aspects and source.retrieval == item.retrieval
    assert source.imported_at == item.imported_at and source.context == item.context
    assert source.references == item.references and source.classifications == item.classifications
    assert (await bridge.resolve_citation(source.id)).text == item.text
    assert service.resolve_citation(f"kg:{item.item_id}").item_id == item.item_id
    assert service.resolve_citation(item.aspects[0].aspect_id) == item.aspects[0]
    assert service.resolve_citation(item.references[0].source_id).source_version is None
    assert service.resolve_citation("evidence:other:synthetic") is None
    assert service.resolve_citation(feedback_id("bmw-feedback", "absent")) is None


async def test_request_resolution_uses_live_coverage_without_inventing_product_metadata(
    feedback_bridge,
):
    brief = await resolve_request(AnalysisRequest(model_code="G70", regions=["US"]))
    assert brief.reference_model.segment == "unknown" and not brief.reference_model.sold_regions
    assert brief.regions == brief.markets == ["US"]
    assert brief.competitors == [] and brief.warnings
    assert brief.reference_model.data_coverage == {"feedback_dataset": ["US"]}
    service, bridge = feedback_bridge
    model = await bridge.resolve_citation(f"kg:{brief.reference_model.node_id}")
    assert model == service.get_model("G70")
    registry = await load_registry()
    assert set(registry.models) == {"G70"} and set(registry.regions) == {"US"}
    with pytest.raises(ValueError, match="unknown model"):
        registry.check(AnalysisRequest(model_code="G68"))


def test_application_profiles_are_explicit_and_dont_replace_feedback_coverage():
    service = FeedbackKnowledgeService(
        MemoryFeedbackRepository(),
        FeedbackServiceConfig(
            model_profiles={
                "G70": ModelProfile(
                    segment="invented-segment",
                    curation_note="Synthetic application curation.",
                    sold_regions=["ZZ"],
                )
            }
        ),
    )
    model = service.get_model("G70")
    assert model.segment == "invented-segment" and model.regions == ["US"]
    assert model.sold_regions == ["ZZ"]
    assert service.get_model("NOT_IMPORTED") is None


async def test_missing_data_is_explicit_and_optional_snapshot_methods_stay_compatible(
    feedback_bridge,
):
    _, bridge = feedback_bridge
    availability = await bridge.get_data_availability()
    assert {value.kind for value in availability if value.status == "available"} == {"feedback"}
    for call in (
        bridge.sales_volume(["G70"]),
        bridge.get_study_scores(["G70"], ["US"]),
        bridge.get_attribute_values("G70"),
        bridge.search_documents("synthetic"),
        bridge.list_portfolio(),
    ):
        with pytest.raises(KnowledgeUnavailableError):
            await call
    assert await bridge.get_taxonomy() is None
    assert await bridge.store_findings({}) is False
    legacy = ModuleBackend(SimpleNamespace(), None)
    assert await legacy.get_feedback_page(FeedbackFilter()) is None
    assert await legacy.get_data_availability() is None


async def test_registry_failure_and_empty_coverage_never_advertise_yaml_models():
    async def broken():
        raise FeedbackStorageError("Synthetic unavailable database")

    set_backend(SimpleNamespace(list_supported_models=broken))
    with pytest.raises(FeedbackStorageError):
        await load_registry()

    async def empty():
        return []

    async def empty_regions():
        return {}

    set_backend(SimpleNamespace(list_supported_models=empty, list_regions=empty_regions))
    result = await load_registry()
    assert result.models == {} and result.regions == {}


async def test_inspection_exercises_sql_projection_bridge_and_citation_resolution(feedback_bridge):
    service, _ = feedback_bridge
    result = await inspect_service(service, derivate="G70", country="US", limit=50)
    assert result["feedback"]["total_matching"] == 1 and result["aspects_in_selection"] == 1
    assert result["citation_checks_passed"] == 2
    assert result["request_has_feedback_coverage"] is True
    assert VERBATIM not in str(result) and "synthetic feedback/one" not in str(result)


async def test_real_feedback_agent_consumes_projected_sql_aspects_with_fake_providers(
    feedback_bridge, monkeypatch
):
    service, _ = feedback_bridge
    # The fixture holds one item; the agent normally reports features mentioned by >= 3 items.
    monkeypatch.setattr(load_rules().feedback, "min_k", 1)
    brief = await resolve_request(AnalysisRequest(model_code="G70", regions=["US"]))
    ctx = AgentContext("feedback", brief, await load_taxonomy())
    await feedback.run(ctx)
    report = ctx.build_report()
    assert report.status == "ok" and report.findings
    assert report.stats["n_items"] == report.stats["n_after_dedupe"] == 1
    assert report.sources and report.sources[0].aspects
    source = Source.model_validate_json(report.sources[0].model_dump_json())
    assert service.resolve_citation(source.id).aspects == source.aspects
    assert source.retrieval.total_matching == source.retrieval.returned_count == 1
    assert all(f.quantity.value == 1 for f in report.findings if f.quantity)


def test_sql_coverage_keeps_partial_metadata_unknown_and_citations_are_parameterized():
    repo, _, _ = repository(
        [
            {
                "derivate_code": "G70",
                "countries": ["US", None],
                "engine_types": ["BEV", None],
                "n": 2,
                "brand": None,
                "sales_description": None,
            }
        ]
    )
    coverage = repo.coverage()[0]
    assert coverage.countries == ["US"] and coverage.brand is None
    assert coverage.engine_types == ["BEV"] and coverage.feedback_count == 2
    repo, conn, _ = repository([parent()], [aspect()])
    assert repo.find_feedback("synthetic feedback/one").text == VERBATIM
    assert conn.calls[1][1] == ("synthetic feedback/one",)
    assert "synthetic feedback/one" not in conn.calls[1][0]
    repo, conn, _ = repository([parent()], [aspect()])
    assert repo.find_aspect(str(ASPECT_ID)).aspect_id.endswith(str(ASPECT_ID))
    assert repo.find_aspect("invalid-uuid") is None
