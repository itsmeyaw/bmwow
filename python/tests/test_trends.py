from bmwow.agent.models.evidence import AnalysisRequest
from bmwow.agent.nodes import trends
from bmwow.agent.nodes.common import AgentContext
from bmwow.agent.resolve import resolve_request
from bmwow.agent.sources import Budget
from bmwow.agent.taxonomy import load_taxonomy
from bmwow.knowledge import KnowledgeUnavailableError
from tests.fakes import ontology as fake_ontology
from tests.fakes.data import REF_CODE


async def run_trends():
    brief = await resolve_request(AnalysisRequest(model_code=REF_CODE, regions=["EU", "CN"]))
    ctx = AgentContext("trends", brief, await load_taxonomy(), budget=Budget(20, 25))
    await trends.run(ctx)
    return ctx, ctx.build_report()


async def test_trend_findings_carry_horizon_direction_and_source_count():
    ctx, report = await run_trends()
    assert report.findings
    for f in report.findings:
        assert f.horizon in {"now", "1-2y", "3y+"}
        assert f.direction in {"request", "problem", "neutral"}
        assert f.n_independent_sources is not None and f.n_independent_sources >= 1
    # the fake cites one source per trend: every trend is backed by a single source (thin)
    assert all(f.n_independent_sources == 1 for f in report.findings)
    assert {a.source: a.status for a in report.availability}["documents"] == "ok"


async def test_independent_sources_count_domains_and_documents():
    ctx, report = await run_trends()
    web = [s.id for s in report.sources if s.kind == "web"]
    docs = [s.id for s in report.sources if s.kind == "ontology"]
    assert trends.independent_sources(ctx, web + web) == len(
        {ctx.registry.get(i).ref.split("/")[2] for i in web}
    )
    assert trends.independent_sources(ctx, docs[:2] + ["kg:missing"]) == len(docs[:2])


async def test_missing_documents_are_reported_and_the_web_loop_still_runs(monkeypatch):
    def not_connected(*args, **kwargs):
        raise KnowledgeUnavailableError("Documents is not connected.")

    monkeypatch.setattr(fake_ontology, "search_documents", not_connected)
    _, report = await run_trends()
    docs = next(a for a in report.availability if a.source == "documents")
    assert docs.status == "unavailable" and "not connected" in docs.reason
    assert report.status == "ok" and report.findings  # the web loop still produced trends


async def test_stored_documents_tool_reports_errors_to_the_model(monkeypatch):
    from bmwow.agent.sources import Budget, SourceRegistry
    from bmwow.agent.tools.graph_rag import make_graph_tools

    def not_connected(*args, **kwargs):
        raise KnowledgeUnavailableError("Documents is not connected.")

    monkeypatch.setattr(fake_ontology, "search_documents", not_connected)
    (tool,) = make_graph_tools(SourceRegistry(), Budget(5, 5), ["EU"])
    out = await tool.ainvoke({"query": "charging"})
    assert out.startswith("ERROR: stored documents are not available")
