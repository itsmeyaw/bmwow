import types

import pytest

from bmwow.agent import service
from bmwow.agent.models.evidence import AnalysisRequest
from bmwow.agent.registry import ResolveError, load_registry
from bmwow.agent.resolve import resolve_request
from bmwow.agent.supervisor import build_graph
from bmwow.agent.tools import knowledge
from tests.fakes.data import CN_ONLY_CODE, EU_ONLY_COMPETITORS, REF_CODE, SEGMENT


@pytest.fixture(autouse=True)
async def close_service():
    yield
    await service.aclose()


async def test_eu_request_resolves_segment_markets_and_competitors():
    brief = await resolve_request(AnalysisRequest(model_code="test01", regions=["eu"]))
    assert brief.model_code == REF_CODE and brief.reference_model.attributes
    assert brief.segment == SEGMENT and brief.regions == ["EU"] and brief.markets == ["DE", "FR"]
    assert {c.name for c in brief.competitors} == {"Competitor A Sedan", *EU_ONLY_COMPETITORS}
    assert all(c.regions == ["EU"] for c in brief.competitors)
    assert brief.search_locale["EU"].country == "de" and brief.focus_areas == []


@pytest.mark.parametrize("regions", [None, []])
async def test_no_regions_means_all_regions_the_model_has_data_for(regions):
    brief = await resolve_request(AnalysisRequest(model_code=REF_CODE, regions=regions))
    assert brief.regions == ["EU", "CN"] and set(brief.search_locale) == {"EU", "CN"}
    cn_only = await resolve_request(AnalysisRequest(model_code=CN_ONLY_CODE))
    assert cn_only.regions == ["CN"] and cn_only.markets == ["CN"]
    out = await build_graph().ainvoke(
        {"run_id": "all", "request": AnalysisRequest(model_code=REF_CODE)}
    )
    assert out["analysis"].brief.regions == ["EU", "CN"]
    assert {r.status for r in out["analysis"].reports.values()} == {"ok"}


async def test_competitors_are_tagged_with_the_requested_regions_they_are_sold_in():
    brief = await resolve_request(AnalysisRequest(model_code=REF_CODE, regions=["EU", "CN"]))
    regions = {c.name: c.regions for c in brief.competitors}
    assert regions == {
        "Competitor A Sedan": ["EU", "CN"],
        "Competitor B Sedan": ["EU"],
        "Competitor C Sedan": ["CN"],
        "Competitor D Sedan": ["EU"],
    }
    assert not brief.warnings


@pytest.mark.parametrize(
    "request_kwargs, message",
    [
        ({"model_code": "G99", "regions": ["EU"]}, f"valid codes: {REF_CODE}, {CN_ONLY_CODE}"),
        ({"model_code": REF_CODE, "regions": ["XX"]}, "valid regions: EU, CN"),
        ({"model_code": CN_ONLY_CODE, "regions": ["EU"]}, "it supports: CN"),
    ],
)
async def test_invalid_requests_fail_fast_and_no_agent_runs(request_kwargs, message):
    request = AnalysisRequest(**request_kwargs)
    with pytest.raises(ResolveError, match=message):
        await service.resolve(request)
    out = await build_graph().ainvoke({"run_id": "bad", "request": request})
    assert message in out["resolve_error"]
    assert not out.get("reports") and "analysis" not in out  # `reports` is only the reducer default


async def test_start_analysis_rejects_unsupported_input_before_launching():
    with pytest.raises(ResolveError, match="it supports: CN"):
        await service.start_analysis(AnalysisRequest(model_code=CN_ONLY_CODE, regions=["EU"]))
    assert not service._runs


def test_request_has_only_model_code_and_regions():
    assert set(AnalysisRequest.model_fields) == {"model_code", "regions"}


async def test_list_models_comes_from_the_knowledge_layer():
    models = await service.list_models()
    assert {(m.model_code, tuple(m.regions)) for m in models} == {
        (REF_CODE, ("EU", "CN")),
        (CN_ONLY_CODE, ("CN",)),
    }


async def test_registry_falls_back_to_yaml_without_the_optional_contracts():
    knowledge.set_backend(knowledge.ModuleBackend(types.SimpleNamespace(), types.SimpleNamespace()))
    registry = await load_registry()
    assert set(registry.models) == {"G60", "F70", "G68"} and set(registry.regions) >= {
        "EU",
        "US",
        "CN",
    }
    with pytest.raises(ResolveError, match="it supports: CN"):
        registry.check(AnalysisRequest(model_code="G68", regions=["EU"]))


@pytest.mark.parametrize("method", ["list_supported_models", "list_regions"])
async def test_registry_backend_errors_surface_before_a_run_starts(
    method, analysis_request, monkeypatch
):
    async def broken():
        raise RuntimeError(f"synthetic {method} failure")

    monkeypatch.setattr(knowledge.get_backend(), method, broken)
    with pytest.raises(RuntimeError, match=f"synthetic {method} failure"):
        await service.start_analysis(analysis_request)
    assert not service._runs and not service._graph_cache
    out = await build_graph().ainvoke({"run_id": "registry-failure", "request": analysis_request})
    assert f"synthetic {method} failure" in out["resolve_error"]
    assert not out.get("reports") and "analysis" not in out


@pytest.mark.parametrize("method", ["list_supported_models", "list_regions"])
async def test_empty_registry_results_do_not_use_yaml(method, monkeypatch):
    async def empty():
        return [] if method == "list_supported_models" else {}

    monkeypatch.setattr(knowledge.get_backend(), method, empty)
    registry = await load_registry()
    assert not (registry.models if method == "list_supported_models" else registry.regions)


async def test_brief_override_is_used_instead_of_re_resolving():
    request = AnalysisRequest(model_code=REF_CODE, regions=["EU"])
    brief = await service.resolve(request)
    corrected = brief.model_copy(
        update={"focus_areas": ["Interior"], "competitors": brief.competitors[:1]}
    )
    run_id = await service.start_analysis(request, brief_override=corrected)
    await service._runs[run_id].task
    status = await service.get_analysis(run_id)
    assert (
        status.state == "done" and status.analysis.brief == corrected and status.brief == corrected
    )
    assert status.analysis.reports["competition"].stats["n_competitors"] == 1

    wrong = brief.model_copy(
        update={"regions": ["EU", "CN"]}
    )  # CN has no locale/markets in this brief
    with pytest.raises(ResolveError):
        await service.start_analysis(request, brief_override=wrong)
