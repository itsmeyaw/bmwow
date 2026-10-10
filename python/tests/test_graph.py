import asyncio
import re

from langgraph.graph import START, StateGraph

from bmwow.agent import supervisor
from bmwow.agent.config import get_settings
from bmwow.agent.models.evidence import AGENT_NAMES, SituationAnalysis
from bmwow.agent.resolve import resolve_request
from bmwow.agent.state import AnalysisState, merge_dict
from bmwow.agent.supervisor import build_graph, build_subgraph
from bmwow.agent.tools import web_search
from tests.fakes import ontology as fake_ontology
from tests.fakes.web import NoNetworkProvider


def assert_all_sources_resolve(analysis: SituationAnalysis) -> None:
    for agent, report in analysis.reports.items():
        ids = {s.id for s in report.sources}
        for f in report.findings:
            assert re.fullmatch(rf"F-{agent}-\d+", f.id)
            assert f.source_ids and set(f.source_ids) <= ids, (f.id, f.source_ids)
        for s in report.sources:
            assert s.excerpt.strip() and len(s.excerpt) <= 1200


async def test_full_run_then_offline_rerun_all_sources_resolve(analysis_request, monkeypatch):
    # 1. record the web cache with the fake provider
    first = (await build_graph().ainvoke({"run_id": "rec", "request": analysis_request}))[
        "analysis"
    ]
    assert set(first.reports) == set(AGENT_NAMES)
    # 2. offline: only the cache may be used
    monkeypatch.setenv("OFFLINE_MODE", "true")
    get_settings.cache_clear()
    web_search.set_search_backend(
        web_search.CachedSearchBackend(
            NoNetworkProvider(), get_settings().web_cache_dir, offline=True
        )
    )
    analysis = (await build_graph().ainvoke({"run_id": "offline", "request": analysis_request}))[
        "analysis"
    ]
    assert {a: r.status for a, r in analysis.reports.items()} == {a: "ok" for a in AGENT_NAMES}
    assert_all_sources_resolve(analysis)
    assert len(analysis.reports["competition"].findings) == len(
        first.reports["competition"].findings
    )
    stats = analysis.reports["competition"].stats
    assert stats["n_from_web"] > 0 and stats["n_from_ontology"] > 0
    # web numbers are in the cited excerpts; the planted 999 km never survives
    for f in analysis.reports["competition"].findings:
        assert "999" not in f.claim
    # persisted + handed to the optional ontology contract
    saved = get_settings().analyses_dir / "offline.json"
    assert SituationAnalysis.model_validate_json(saved.read_text()).run_id == "offline"
    assert fake_ontology.stored_analyses[-1].run_id == "offline"


async def test_validator_strips_invented_numbers_in_competition(analysis_request):
    report = (await build_graph().ainvoke({"run_id": "c", "request": analysis_request}))[
        "analysis"
    ].reports["competition"]
    assert (
        report.stats["dropped_findings"] >= 4
    )  # 999-km claims and dangling web:deadbeef citations
    web_ids = {s.id for s in report.sources if s.kind == "web"}
    assert "web:deadbeef" not in web_ids
    for f in report.findings:
        if f.quantity and f.quantity.origin == "source_text":
            excerpt = " ".join(s.excerpt for s in report.sources if s.id in f.source_ids)
            assert f"{f.quantity.value:g}" in excerpt.replace(",", "")


async def test_trends_failure_is_isolated(analysis_request):
    async def boom(ctx):
        raise RuntimeError("trends exploded")

    analysis = (
        await build_graph(agents={"trends": boom}).ainvoke(
            {"run_id": "boom", "request": analysis_request}
        )
    )["analysis"]
    assert isinstance(analysis, SituationAnalysis)
    assert analysis.reports["trends"].status == "failed"
    assert "trends exploded" in analysis.reports["trends"].errors[0]
    assert all(analysis.reports[a].status == "ok" for a in ("baseline", "competition", "feedback"))


async def test_timeout_keeps_partial_findings(analysis_request, monkeypatch):
    monkeypatch.setenv("AGENT_TIMEOUT_S", "1")
    get_settings.cache_clear()

    async def slow(ctx):
        from bmwow.agent.nodes.baseline import run

        await run(ctx)
        await asyncio.sleep(5)

    analysis = (
        await build_graph(agents={"baseline": slow}).ainvoke(
            {"run_id": "slow", "request": analysis_request}
        )
    )["analysis"]
    report = analysis.reports["baseline"]
    assert report.status == "partial" and report.findings and "timeout" in report.errors[0]


async def test_collect_fills_missing_reports(analysis_request):
    brief = await resolve_request(analysis_request)
    out = await supervisor.collect(
        {"run_id": "x", "request": analysis_request, "brief": brief, "reports": {}}
    )
    assert {r.status for r in out["analysis"].reports.values()} == {"failed"}


def test_merge_dict_reducer():
    assert merge_dict({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert merge_dict(None, {"b": 2}) == {"b": 2}


async def test_subgraph_mounts_as_one_node(analysis_request):
    parent = StateGraph(AnalysisState)
    parent.add_node("situation_analysis", build_subgraph())
    parent.add_edge(START, "situation_analysis")
    out = await parent.compile().ainvoke({"run_id": "sub", "request": analysis_request})
    assert set(out["analysis"].reports) == set(AGENT_NAMES)


async def test_competitor_discovery_when_ontology_has_none(analysis_request, monkeypatch):
    monkeypatch.setattr(
        fake_ontology, "list_competitor_models", lambda segment, regions, names=None: []
    )
    from tests.fakes import llm as fake_llm

    original = fake_llm.FakeAnalyst._competition

    def discover_or_research(self, messages, prompt):
        if "competitive set" in prompt and "# Competitor\n" not in prompt:
            if not any(isinstance(m, fake_llm.ToolMessage) for m in messages):
                return fake_llm._call("web_search", {"query": "Competitor B Sedan review"})
            sid = re.search(r"\[(web:[0-9a-f]{8})\] Competitor B", str(messages[-1].content)).group(
                1
            )
            quote = "In our test the Competitor B Sedan charged from 10-80% in 22 minutes."
            return fake_llm._call(
                "DraftFindings",
                {
                    "findings": [
                        {
                            "attribute": "unmapped:competitive_set",
                            "claim": "Competitor B Sedan competes as a BEV sedan.",
                            "polarity": "neutral",
                            "subject": "Competitor B Sedan",
                            "value": None,
                            "unit": None,
                            "qualifier": "",
                            "source_ids": [sid],
                            "evidence_quote": quote,
                            "confidence": "medium",
                        }
                    ]
                },
            )
        return original(self, messages, prompt)

    monkeypatch.setattr(fake_llm.FakeAnalyst, "_competition", discover_or_research)
    report = (await build_graph().ainvoke({"run_id": "disc", "request": analysis_request}))[
        "analysis"
    ].reports["competition"]
    assert report.stats["n_competitors"] == 1 and report.stats["n_from_ontology"] == 0
    assert any(f.attribute == "unmapped:competitive_set" for f in report.findings)
    assert any(f.attribute == "fast_charging" and f.quantity for f in report.findings)
