"""AGENT_SPEC §6.0.10: every knowledge-layer call carries regions or markets, every web search a locale."""

import inspect

import pytest

from src.agent.supervisor import build_graph
from src.models.evidence import AnalysisRequest
from tests.fakes import ontology as fake_ontology
from tests.fakes import sql_client as fake_sql
from tests.fakes.data import EU_ONLY_COMPETITORS, REF_CODE, REGIONS

# function -> the argument that scopes it. get_model / get_attribute_values address one model by id and
# are not region-scoped by contract (§4.1).
SCOPED = {
    (fake_ontology, "list_portfolio"): "regions",
    (fake_ontology, "list_competitor_models"): "regions",
    (fake_ontology, "search_documents"): "regions",
    (fake_ontology, "get_feedback_items"): "filters",
    (fake_sql, "sales_volume"): "markets",
}


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple[str, list[str]]] = []
    for (module, name), arg in SCOPED.items():
        fn = getattr(module, name)

        def spy(*args, _fn=fn, _name=name, _arg=arg, **kwargs):
            value = inspect.signature(_fn).bind(*args, **kwargs).arguments.get(_arg)
            scope = value.markets if _arg == "filters" else value
            seen.append((_name, list(scope or [])))
            return _fn(*args, **kwargs)

        monkeypatch.setattr(module, name, spy)
    return seen


def _markets(regions: list[str]) -> set[str]:
    return {m for r in regions for m in REGIONS[r]["markets"]}


@pytest.mark.parametrize("regions", [["CN"], ["EU", "CN"]])
async def test_every_data_call_is_region_scoped(regions, calls, fake_env):
    out = await build_graph().ainvoke(
        {"run_id": "scope", "request": AnalysisRequest(model_code=REF_CODE, regions=regions)}
    )
    assert {r.status for r in out["analysis"].reports.values()} == {"ok"}
    assert {name for name, _ in calls} == {name for _, name in SCOPED}
    allowed = set(regions) | _markets(regions)
    for name, scope in calls:
        assert scope and set(scope) <= allowed, (name, scope)
    searches = fake_env["provider"].searches
    assert searches and all(locale is not None for _, locale in searches)
    assert {locale.country for _, locale in searches} <= {
        REGIONS[r]["search"]["country"] for r in regions
    }


async def test_cn_run_never_touches_eu_only_competitors(fake_env):
    out = await build_graph().ainvoke(
        {"run_id": "cn", "request": AnalysisRequest(model_code=REF_CODE, regions=["CN"])}
    )
    brief = out["brief"]
    assert {c.name for c in brief.competitors} == {"Competitor A Sedan", "Competitor C Sedan"}
    assert brief.markets == ["CN"]
    queries = " ".join(q for q, _ in fake_env["provider"].searches)
    report = out["analysis"].reports["competition"]
    for name in EU_ONLY_COMPETITORS:
        assert name not in queries
        assert all(f.subject != name for f in report.findings)
    assert report.stats["n_competitors"] == 2 and report.stats["n_competitors:CN"] == 2
    baseline = out["analysis"].reports["baseline"]
    assert not any(
        q.qualifier.endswith(("DE", "FR", "EU"))
        for q in (f.quantity for f in baseline.findings)
        if q
    )
