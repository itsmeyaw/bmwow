from __future__ import annotations

import pytest

from bmwow.agent import llm, service
from bmwow.agent.config import get_settings
from bmwow.agent.models.evidence import AnalysisRequest
from bmwow.agent.tools import knowledge, web_search
from tests.fakes.data import REF_CODE
from tests.fakes.knowledge import FakeKnowledge
from tests.fakes.llm import fake_models
from tests.fakes.web import FakePageProvider


@pytest.fixture(autouse=True)
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KNOWLEDGE_BACKEND", "fake")
    monkeypatch.setenv("OFFLINE_MODE", "false")
    monkeypatch.setenv("SEARCH_BACKEND", "firecrawl")  # tests never depend on the local .env
    monkeypatch.setenv("AGENT_TIMEOUT_S", "60")
    # Synthetic data only: the LLM steps that would see BMW data run against the fake models.
    monkeypatch.setenv("ALLOW_LLM_ON_INTERNAL_DATA", "true")
    get_settings.cache_clear()
    knowledge.set_backend(FakeKnowledge())
    provider = FakePageProvider()
    web_search.set_search_backend(
        web_search.CachedSearchBackend(provider, get_settings().web_cache_dir, offline=False)
    )
    strong, cheap, emb, analyst = fake_models()
    llm.set_overrides(strong=strong, cheap=cheap, embeddings=emb)
    yield {"provider": provider, "analyst": analyst, "tmp": tmp_path}
    llm.set_overrides()
    knowledge.set_backend(None)
    web_search.set_search_backend(None)
    service._runs.clear()
    service._graph_cache.clear()
    get_settings.cache_clear()


@pytest.fixture
def analysis_request() -> AnalysisRequest:
    """`TEST01` in both fake regions."""
    return AnalysisRequest(model_code=REF_CODE, regions=["EU", "CN"])
