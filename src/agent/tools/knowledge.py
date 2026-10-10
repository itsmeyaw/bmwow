"""Adapter to the knowledge layer (AGENT_SPEC §4): the only coupling between agents and `knowledge/`.

The record types (`src/models/knowledge.py`, re-exported here) are the minimum fields the agents rely
on. When the real `src.knowledge` modules land with different names or shapes, change `ModuleBackend`
(or add another backend) here; the agents only see `KnowledgeBackend`.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Iterable
from typing import Any, Protocol

from pydantic import BaseModel

from src.models.knowledge import (  # noqa: F401
    AttributeValue,
    DocChunk,
    FeedbackFilter,
    FeedbackItem,
    ModelNode,
    SalesRow,
    StudyScore,
)

from ..config import get_settings


class KnowledgeBackend(Protocol):
    async def get_model(self, model_code: str) -> ModelNode | None: ...
    async def list_portfolio(
        self, segment: str | None = None, regions: list[str] | None = None
    ) -> list[ModelNode]: ...
    async def list_competitor_models(
        self, segment: str, regions: list[str], names: list[str] | None = None
    ) -> list[ModelNode]: ...
    async def get_attribute_values(
        self, model_id: str, attributes: list[str] | None = None
    ) -> list[AttributeValue]: ...
    async def get_feedback_items(self, filters: FeedbackFilter) -> list[FeedbackItem]: ...
    async def search_documents(
        self,
        query: str,
        kinds: list[str] | None = None,
        regions: list[str] | None = None,
        k: int = 10,
    ) -> list[DocChunk]: ...
    async def sales_volume(
        self,
        models: list[str],
        markets: list[str] | None = None,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> list[SalesRow]: ...
    async def list_supported_models(self) -> list[dict[str, Any]] | None: ...
    async def list_regions(self) -> dict[str, dict[str, Any]] | None: ...
    async def get_taxonomy(self) -> dict[str, list[str]] | None: ...
    async def get_study_scores(self, models: list[str], regions: list[str]) -> list[StudyScore]: ...
    async def store_findings(self, analysis: Any) -> bool: ...


def _coerce[T: BaseModel](cls: type[T], obj: Any) -> T:
    return obj if isinstance(obj, cls) else cls.model_validate(obj)


def _coerce_all[T: BaseModel](cls: type[T], objs: Iterable[Any]) -> list[T]:
    return [_coerce(cls, o) for o in objs]


class ModuleBackend:
    """Calls module-level functions with the §4 signatures (sync or async) and coerces the results.

    Sync functions run in a worker thread so they never block the parallel agents.
    """

    def __init__(self, ontology: Any, sql_client: Any) -> None:
        self.ontology = ontology
        self.sql = sql_client

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _optional(self, name: str, *args: Any) -> Any:
        fn = getattr(self.ontology, name, None)
        return await self._run(fn, *args) if fn else None

    async def get_model(self, model_code: str) -> ModelNode | None:
        model = await self._run(self.ontology.get_model, model_code)
        return None if model is None else _coerce(ModelNode, model)

    async def list_portfolio(
        self, segment: str | None = None, regions: list[str] | None = None
    ) -> list[ModelNode]:
        return _coerce_all(
            ModelNode, await self._run(self.ontology.list_portfolio, segment, regions)
        )

    async def list_competitor_models(
        self, segment: str, regions: list[str], names: list[str] | None = None
    ) -> list[ModelNode]:
        return _coerce_all(
            ModelNode,
            await self._run(self.ontology.list_competitor_models, segment, regions, names),
        )

    async def get_attribute_values(
        self, model_id: str, attributes: list[str] | None = None
    ) -> list[AttributeValue]:
        return _coerce_all(
            AttributeValue,
            await self._run(self.ontology.get_attribute_values, model_id, attributes),
        )

    async def get_feedback_items(self, filters: FeedbackFilter) -> list[FeedbackItem]:
        # The contract allows an iterable; materialise it (bounded by filters.limit).
        items = await self._run(self.ontology.get_feedback_items, filters)
        return _coerce_all(FeedbackItem, list(items))

    async def search_documents(
        self,
        query: str,
        kinds: list[str] | None = None,
        regions: list[str] | None = None,
        k: int = 10,
    ) -> list[DocChunk]:
        return _coerce_all(
            DocChunk, await self._run(self.ontology.search_documents, query, kinds, regions, k)
        )

    async def sales_volume(
        self,
        models: list[str],
        markets: list[str] | None = None,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> list[SalesRow]:
        rows = await self._run(self.sql.sales_volume, models, markets, period_from, period_to)
        return _coerce_all(SalesRow, rows)

    async def list_supported_models(self) -> list[dict[str, Any]] | None:
        """Optional contract (§4.5). None = fall back to src/agent/models.yaml."""
        return await self._optional("list_supported_models")

    async def list_regions(self) -> dict[str, dict[str, Any]] | None:
        """Optional contract (§4.4). None = fall back to src/agent/regions.yaml."""
        return await self._optional("list_regions")

    async def get_taxonomy(self) -> dict[str, list[str]] | None:
        return await self._optional("get_taxonomy")

    async def get_study_scores(self, models: list[str], regions: list[str]) -> list[StudyScore]:
        rows = await self._optional("get_study_scores", models, regions)
        return _coerce_all(StudyScore, rows or [])

    async def store_findings(self, analysis: Any) -> bool:
        """Optional contract (§7). Returns False when the ontology does not provide it."""
        fn = getattr(self.ontology, "store_findings", None)
        if fn is None:
            return False
        await self._run(fn, analysis)
        return True


_backend: KnowledgeBackend | None = None


def set_backend(backend: KnowledgeBackend | None) -> None:
    global _backend
    _backend = backend


def get_backend() -> KnowledgeBackend:
    global _backend
    if _backend is None:
        if get_settings().knowledge_backend == "fake":
            from tests.fakes.knowledge import FakeKnowledge

            _backend = FakeKnowledge()
        else:
            _backend = ModuleBackend(
                importlib.import_module("src.knowledge.ontology"),
                importlib.import_module("src.knowledge.sql_client"),
            )
    return _backend
