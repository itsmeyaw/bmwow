from pathlib import Path

import pytest

from bmwow.agent.config import get_settings
from bmwow.agent.knowledge_bridge import configure_service
from bmwow.agent.tools.knowledge import get_backend, set_backend
from bmwow.knowledge import create_synthetic_service
from bmwow.ontology import GraphBundle


@pytest.fixture
def bundle():
    path = Path(__file__).resolve().parents[3] / "contracts/ontology/examples/synthetic.json"
    return GraphBundle.model_validate_json(path.read_text(encoding="utf-8"))


@pytest.fixture
def knowledge_service(bundle):
    return create_synthetic_service(bundle)


@pytest.fixture
def bridge(fake_env, knowledge_service, monkeypatch):
    # Use the new real-module boundary while the outer fixture blocks live LLM/search calls.
    configure_service(knowledge_service)
    monkeypatch.setenv("KNOWLEDGE_BACKEND", "real")
    get_settings.cache_clear()
    set_backend(None)
    yield get_backend()
    configure_service(None)
    set_backend(None)
    get_settings.cache_clear()
