from bmwow.agent.models.evidence import AnalysisRequest
from bmwow.agent.nodes import baseline
from bmwow.agent.nodes.common import AgentContext
from bmwow.agent.resolve import resolve_request
from bmwow.agent.taxonomy import load_taxonomy
from bmwow.knowledge import KnowledgeUnavailableError
from tests.fakes import ontology as fake_ontology


async def run_baseline(request: AnalysisRequest):
    brief = await resolve_request(request)
    ctx = AgentContext("baseline", brief, await load_taxonomy())
    await baseline.run(ctx)
    return ctx.build_report()


async def test_baseline_reports_missing_sources_and_never_calls_an_llm(
    analysis_request, monkeypatch, fake_env
):
    def not_connected(segment=None, regions=None):
        raise KnowledgeUnavailableError("Portfolio is not connected to the feedback-only backend.")

    monkeypatch.setattr(fake_ontology, "list_portfolio", not_connected)
    report = await run_baseline(analysis_request)
    status = {a.source: a.status for a in report.availability}
    assert status["portfolio"] == "unavailable" and status["catalog"] == "ok"
    assert status["studies"] == "unavailable"  # the fake knowledge layer has no study scores
    assert report.findings and not any("portfolio" in e for e in report.errors)
    assert all(f.direction in (None, "neutral") for f in report.findings)
    assert fake_env["analyst"].prompts == []  # facts only: no positioning call
