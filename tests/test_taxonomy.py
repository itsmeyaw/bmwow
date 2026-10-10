from types import SimpleNamespace

import pytest

from src.agent.nodes.common import agent_node
from src.agent.resolve import resolve_request
from src.agent.taxonomy import load_taxonomy
from src.agent.tools import knowledge


async def test_taxonomy_falls_back_when_optional_contract_is_absent():
    knowledge.set_backend(knowledge.ModuleBackend(SimpleNamespace(), SimpleNamespace()))
    taxonomy = await load_taxonomy()
    assert "comfortable_seats" in taxonomy.attributes


async def test_empty_taxonomy_is_authoritative(monkeypatch):
    async def empty():
        return {}

    monkeypatch.setattr(knowledge.get_backend(), "get_taxonomy", empty)
    taxonomy = await load_taxonomy()
    assert taxonomy.areas == {} and taxonomy.attributes == []


async def test_taxonomy_error_is_reported_without_running_agent(analysis_request, monkeypatch):
    brief = await resolve_request(analysis_request)

    async def broken():
        raise RuntimeError("synthetic taxonomy failure")

    monkeypatch.setattr(knowledge.get_backend(), "get_taxonomy", broken)
    with pytest.raises(RuntimeError, match="synthetic taxonomy failure"):
        await load_taxonomy()

    async def must_not_run(ctx):
        pytest.fail("agent ran despite taxonomy failure")

    out = await agent_node("baseline", must_not_run)({"brief": brief})
    report = out["reports"]["baseline"]
    assert report.status == "failed" and not report.findings
    assert report.errors == ["RuntimeError: synthetic taxonomy failure"]
