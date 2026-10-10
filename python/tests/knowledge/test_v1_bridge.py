from types import SimpleNamespace

import pytest

from bmwow.agent.knowledge_bridge import configure_service, get_service
from bmwow.agent.models import knowledge as legacy_records
from bmwow.agent.models.evidence import AGENT_NAMES, AnalysisRequest, SituationAnalysis
from bmwow.agent.nodes import baseline, competition
from bmwow.agent.nodes.common import AgentContext
from bmwow.agent.resolve import resolve_request, tag_regions
from bmwow.agent.sources import attribute_source, doc_source, feedback_source
from bmwow.agent.supervisor import build_graph
from bmwow.agent.taxonomy import Taxonomy
from bmwow.agent.tools import graph_rag, sql_rag
from bmwow.agent.tools.feedback_stats import exact_dedupe
from bmwow.agent.tools.knowledge import ModuleBackend
from bmwow.knowledge import AttributeValue, FeedbackFilter
from bmwow.knowledge import records as canonical_records
from bmwow.ontology import validate_bundle


def test_legacy_imports_reexport_one_record_definition():
    for name in legacy_records.__all__:
        assert getattr(legacy_records, name) is getattr(canonical_records, name)


def test_unconfigured_runtime_has_no_fake_fallback():
    configure_service(None)
    with pytest.raises(RuntimeError, match="not configured"):
        get_service()


async def test_bridge_preserves_qualifications_in_json_coercion(bridge):
    attrs = await bridge.get_attribute_values("vehicle:bmw-g60-fixture-ev")
    wire = attrs[0].model_dump(mode="json")
    round_trip = AttributeValue.model_validate(wire)
    assert round_trip == attrs[0]
    assert round_trip.references[0].evidence_id.startswith("evidence:")
    assert round_trip.context.country_codes == ["US"]
    assert await bridge.get_study_scores(["G60"], ["US"])
    assert await bridge.store_findings({"run_id": "synthetic"}) is False


async def test_async_feedback_modules_are_supported():
    async def get_feedback_items(filters):
        return iter([{"item_id": "synthetic:async", "text": "Invented comment", "channel": None}])

    bridge = ModuleBackend(SimpleNamespace(get_feedback_items=get_feedback_items), None)
    assert (await bridge.get_feedback_items(FeedbackFilter()))[0].item_id == "synthetic:async"
    assert await bridge.get_study_scores(["G60"], ["US"]) == []


async def test_sources_retain_original_metadata(bridge, knowledge_service):
    variant = await bridge.get_model("vehicle:bmw-g60-fixture-ev")
    interval = next(value for value in variant.attributes if value.value_range)
    source = attribute_source(variant, interval)
    assert source.measurement.value_range == interval.value_range
    assert source.epistemic_status == interval.epistemic_status
    assert source.references == interval.references and source.context == interval.context
    assert knowledge_service.resolve_citation(source.id).id == interval.node_id
    item = (await bridge.get_feedback_items(FeedbackFilter()))[0]
    feedback = feedback_source(item)
    assert feedback.references == item.references and feedback.limitations == item.limitations
    assert knowledge_service.resolve_citation(feedback.id).id == item.item_id
    chunk = (await bridge.search_documents("parking", ["study"], ["US"]))[0]
    document = doc_source(chunk)
    assert document.publication_label == "2026-09" and "2026-09" in document.title
    assert document.measurement == chunk.measurement
    assert document.references == chunk.references


async def test_sql_query_and_row_citations_are_separate(bridge, knowledge_service):
    got = await sql_rag.sales_volume(["G60", "G68"], ["US"])
    query, row = got.sources
    assert query.id.startswith("sql:") and len(got.data) == 1
    assert row.id == "kg:evidence:fixture-sales" and row.ref == "evidence:fixture-sales"
    assert row.model_codes == ["G60", "G68"]
    assert "source_reported_future" in row.excerpt and "G60_G68" in row.excerpt
    assert row.measurement.temporal_status == "source_reported_future"
    assert row.references == got.data[0].references
    assert knowledge_service.resolve_citation(row.id).properties.measurement == row.measurement


async def test_identical_comments_from_distinct_records_remain_distinct(bridge):
    original = (await bridge.get_feedback_items(FeedbackFilter()))[0]
    another = original.model_copy(deep=True)
    another.item_id = "evidence:synthetic-other-comment"
    another.references[0].evidence_id = another.item_id
    another.references[0].record_key = "other-comment"
    another.references[0].locator.range = "A3"
    assert len(exact_dedupe([original, original.model_copy(deep=True), another])) == 2
    assert len(exact_dedupe([original, another])) == 2


async def test_resolver_uses_curated_competitor_regions(bridge):
    brief = await resolve_request(AnalysisRequest(model_code="G60", regions=["US"]))
    assert brief.reference_model.node_id == "vehicle:bmw-g60"
    assert brief.markets == ["US"]
    assert len(brief.competitors) == 1
    competitor = brief.competitors[0].model_copy(deep=True)
    competitor.regions = ["EU"]  # Dataset coverage is independent of availability.
    assert tag_regions(competitor, ["US"]).regions == ["US"]
    competitor.sold_regions = []
    assert tag_regions(competitor, ["US"]).regions == []


async def test_unknown_date_does_not_establish_freshness(bridge, knowledge_service):
    brief = await resolve_request(AnalysisRequest(model_code="G60", regions=["US"]))
    ctx = AgentContext("competition", brief, Taxonomy(knowledge_service.get_taxonomy()))
    values = await bridge.get_attribute_values("vehicle:example-sedan")
    assert values and all(value.as_of is None and value.references for value in values)
    task = competition._task(ctx, "Example Sedan", ["US"], values)
    assert task["known"] == []
    assert values[0].attribute in task["attributes"]


async def test_future_group_never_becomes_model_sales_or_growth(bridge, knowledge_service):
    brief = await resolve_request(AnalysisRequest(model_code="G60", regions=["US"]))
    ctx = AgentContext("baseline", brief, Taxonomy(knowledge_service.get_taxonomy()))
    await baseline._sales_findings(ctx, [])
    report = ctx.build_report()
    assert report.status == "partial" and len(report.findings) == 1
    finding = report.findings[0]
    assert "combined group G60_G68" in finding.claim and "source_reported_future" in finding.claim
    assert "sold" not in finding.claim and "changed" not in finding.claim
    assert finding.subject == "G60_G68" and finding.quantity.value == 12400
    assert finding.source_ids == ["kg:evidence:fixture-sales"]
    assert report.sources[0].measurement.temporal_status == "source_reported_future"
    assert report.stats["total_units"] == 0 and report.stats["n_grouped_sales_rows"] == 1


async def test_real_graph_wiring_with_synthetic_readers(bridge, knowledge_service, monkeypatch):
    before = knowledge_service.snapshot().model_dump(mode="json")

    async def read_feedback(ctx):
        for item in await bridge.get_feedback_items(FeedbackFilter(models=["G60"], markets=["US"])):
            source = ctx.add_source(feedback_source(item))
            ctx.add(
                ctx.finding(
                    attribute="parking_control_usability",
                    claim=item.text,
                    polarity="negative",
                    subject="customers",
                    source_ids=[source.id],
                    confidence="low",
                )
            )

    async def read_study(ctx):
        got = await graph_rag.search_documents("parking", ["study"], ["US"])
        for chunk, source in zip(got.data, got.sources, strict=True):
            ctx.add_source(source)
            ctx.add(
                ctx.finding(
                    attribute="parking_control_usability",
                    claim=chunk.text.split("\n")[0],
                    polarity="neutral",
                    subject="study",
                    source_ids=[source.id],
                    confidence="low",
                )
            )

    request = AnalysisRequest(model_code="G60", regions=["US"])
    graph = build_graph(
        agents={"feedback": read_feedback, "competition": read_study, "trends": read_study}
    )
    result = await graph.ainvoke({"run_id": "synthetic-bridge", "request": request})
    analysis = SituationAnalysis.model_validate_json(result["analysis"].model_dump_json())
    assert set(analysis.reports) == set(AGENT_NAMES)
    assert analysis.reports["baseline"].status == "partial"
    for report in analysis.reports.values():
        assert report.findings and report.stats["dropped_findings"] == 0
        sources = {source.id: source for source in report.sources}
        for finding in report.findings:
            assert set(finding.source_ids) <= sources.keys()
        for source in sources.values():
            resolved = knowledge_service.resolve_citation(source.id)
            assert resolved.id == source.ref and source.references
    assert knowledge_service.snapshot().model_dump(mode="json") == before
    assert not validate_bundle(knowledge_service.snapshot())
