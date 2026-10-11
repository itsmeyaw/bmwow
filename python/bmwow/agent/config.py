"""Environment-driven settings: model tiers, budgets, paths (SPEC §8)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").split("#")[0].strip()
    return int(raw) if raw else default


def _str(name: str, default: str = "") -> str:
    # Tolerate inline comments copied from .env.example.
    return os.getenv(name, default).split("#")[0].strip() or default


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    llm_strong: str
    llm_cheap: str
    embedding_model: str
    firecrawl_api_key: str
    search_backend: Literal["firecrawl", "corpus", "openai", "brave"]
    offline_mode: bool
    max_competitors: int
    stale_after_days: int
    max_tool_calls_per_agent: int
    agent_timeout_s: int
    max_pages_scraped_per_agent: int
    knowledge_backend: Literal["real", "fake"]
    data_dir: Path
    feedback_max_items: int
    llm_concurrency: int
    # BMW data may not be sent to an LLM until cleared; steps that would (feedback sub-themes, the
    # structure_agent judgment) are skipped and reported as unavailable while this is false.
    allow_llm_on_internal_data: bool

    @property
    def checkpoint_db(self) -> Path:
        return self.data_dir / "db" / "agent_checkpoints.sqlite"

    @property
    def web_cache_dir(self) -> Path:
        return self.data_dir / "processed" / "web_cache"

    @property
    def web_corpus_dir(self) -> Path:
        return self.data_dir / "web_corpus"

    @property
    def curation_path(self) -> Path:
        """Private curation (feature keys, study-question mappings) beside the knowledge snapshot."""
        return self.data_dir / "knowledge" / "curation.json"

    @property
    def analyses_dir(self) -> Path:
        return self.data_dir / "processed" / "analyses"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        openai_api_key=_str("OPENAI_API_KEY"),
        llm_strong=_str("LLM_STRONG"),
        llm_cheap=_str("LLM_CHEAP"),
        embedding_model=_str("EMBEDDING_MODEL", "text-embedding-3-small"),
        firecrawl_api_key=_str("FIRECRAWL_API_KEY"),
        search_backend=_str("SEARCH_BACKEND", "firecrawl"),  # type: ignore[arg-type]
        offline_mode=_bool("OFFLINE_MODE", False),
        max_competitors=_int("MAX_COMPETITORS", 6),
        stale_after_days=_int("STALE_AFTER_DAYS", 365),
        max_tool_calls_per_agent=_int("MAX_TOOL_CALLS_PER_AGENT", 20),
        agent_timeout_s=_int("AGENT_TIMEOUT_S", 180),
        max_pages_scraped_per_agent=_int("MAX_PAGES_SCRAPED_PER_AGENT", 25),
        knowledge_backend=_str("KNOWLEDGE_BACKEND", "real"),  # type: ignore[arg-type]
        data_dir=Path(_str("DATA_DIR", str(Path(__file__).resolve().parents[3] / "data"))),
        feedback_max_items=_int("FEEDBACK_MAX_ITEMS", 5000),
        llm_concurrency=_int("LLM_CONCURRENCY", 8),
        allow_llm_on_internal_data=_bool("ALLOW_LLM_ON_INTERNAL_DATA", False),
    )
