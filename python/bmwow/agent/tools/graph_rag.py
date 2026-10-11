"""Ontology contracts (§4.1) as source-producing functions and LangChain tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.tools import BaseTool, StructuredTool

from bmwow.agent.models.evidence import Source

from ..sources import Budget, SourceRegistry, doc_source, model_source, study_source
from .knowledge import (
    AttributeValue,
    DocChunk,
    FeedbackFilter,
    FeedbackItem,
    ModelNode,
    StudyScore,
    get_backend,
)


@dataclass
class Retrieved[T]:
    data: T
    sources: list[Source] = field(default_factory=list)


async def get_model(model_code: str) -> Retrieved[ModelNode | None]:
    model = await get_backend().get_model(model_code)
    return Retrieved(model, [model_source(model)] if model is not None else [])


async def list_portfolio(segment: str | None, regions: list[str]) -> Retrieved[list[ModelNode]]:
    models = await get_backend().list_portfolio(segment, regions)
    return Retrieved(models, [model_source(m) for m in models])


async def list_competitor_models(
    segment: str, regions: list[str], names: list[str] | None = None
) -> Retrieved[list[ModelNode]]:
    models = await get_backend().list_competitor_models(segment, regions, names or None)
    return Retrieved(models, [model_source(m) for m in models])


async def get_attribute_values(
    model_id: str, attributes: list[str] | None = None
) -> Retrieved[list[AttributeValue]]:
    # Sources need the model name for rendering; callers build them with sources.attribute_source.
    return Retrieved(await get_backend().get_attribute_values(model_id, attributes))


async def get_feedback_items(filters: FeedbackFilter) -> Retrieved[list[FeedbackItem]]:
    # Sources for feedback are created per representative item by the feedback agent.
    return Retrieved(await get_backend().get_feedback_items(filters))


async def get_study_scores(models: list[str], regions: list[str]) -> Retrieved[list[StudyScore]]:
    scores = await get_backend().get_study_scores(models, regions)
    return Retrieved(scores, [study_source(score) for score in scores])


async def search_documents(
    query: str, kinds: list[str] | None, regions: list[str], k: int = 10
) -> Retrieved[list[DocChunk]]:
    chunks = await get_backend().search_documents(query, kinds, regions, k)
    return Retrieved(chunks, [doc_source(c) for c in chunks])


def render_chunks(chunks: list[DocChunk], max_chars: int = 900) -> str:
    if not chunks:
        return "No matching documents in the knowledge layer."
    parts = []
    for c in chunks:
        text = c.text if len(c.text) <= max_chars else c.text[:max_chars] + "…"
        scope = f"; regions: {', '.join(c.regions)}" if c.regions else ""
        parts.append(f"[kg:{c.node_id}] {c.doc_title} ({c.published or 'n.d.'}{scope})\n{text}")
    return "\n\n".join(parts)


def make_graph_tools(
    registry: SourceRegistry, budget: Budget, regions: list[str]
) -> list[BaseTool]:
    """Tools for bounded agent loops, scoped to the run's regions. Results show citable source ids."""

    async def _search_documents(query: str, k: int = 6) -> str:
        if not budget.take("call"):
            return "BUDGET EXHAUSTED: stop calling tools and return your final answer now."
        chunks = await get_backend().search_documents(
            query, ["study", "report"], regions, min(k, 10)
        )
        for c in chunks:
            registry.add(doc_source(c), full_text=c.text)
        return render_chunks(chunks)

    return [
        StructuredTool.from_function(
            coroutine=_search_documents,
            name="search_documents",
            description="Search studies and reports stored in the knowledge layer. Returns chunks with citable ids [kg:...].",
        )
    ]
