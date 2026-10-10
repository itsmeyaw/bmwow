"""Model factory: strong / cheap chat models and embeddings (AGENT_SPEC §6.0.7, §8).

Models are created with `init_chat_model("openai:<id>")`, so a provider switch is a config change.
`set_overrides` lets tests and offline demos inject fake models without touching agent code.
"""

from __future__ import annotations

from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from .config import get_settings

Tier = Literal["strong", "cheap"]

_overrides: dict[str, object] = {}


class LLMConfigError(RuntimeError):
    pass


def set_overrides(
    *,
    strong: BaseChatModel | None = None,
    cheap: BaseChatModel | None = None,
    embeddings: Embeddings | None = None,
) -> None:
    """Replace the configured models (tests, offline demos). Pass nothing to clear all overrides."""
    if strong is None and cheap is None and embeddings is None:
        _overrides.clear()
        return
    for key, value in (("strong", strong), ("cheap", cheap), ("embeddings", embeddings)):
        if value is not None:
            _overrides[key] = value


def get_chat_model(tier: Tier) -> BaseChatModel:
    if tier in _overrides:
        return _overrides[tier]  # type: ignore[return-value]
    settings = get_settings()
    model_id = settings.llm_strong if tier == "strong" else settings.llm_cheap
    if not model_id:
        raise LLMConfigError(f"LLM_{tier.upper()} is not set; see .env.example")
    return init_chat_model(f"openai:{model_id}", timeout=90, max_retries=2)


def get_embeddings() -> Embeddings:
    if "embeddings" in _overrides:
        return _overrides["embeddings"]  # type: ignore[return-value]
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=get_settings().embedding_model)
