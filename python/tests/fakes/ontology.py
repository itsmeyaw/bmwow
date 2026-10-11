"""In-memory fake of bmwow/agent/knowledge_bridge/ontology.py (§4.1), synchronous like a typical DB client."""

from __future__ import annotations

import re

from bmwow.agent.tools.knowledge import (
    AttributeValue,
    DocChunk,
    FeedbackFilter,
    FeedbackItem,
    ModelNode,
)

from . import data

_MODELS = data.models()
_FEEDBACK = data.feedback()
_DOCS = data.documents()
stored_analyses: list = []


def _find(model_id: str) -> ModelNode | None:
    for m in _MODELS.values():
        if model_id in (m.node_id, m.name, m.model_code):
            return m
    return None


def _in_regions(model_regions: list[str], regions: list[str] | None) -> bool:
    return not regions or not model_regions or bool(set(model_regions) & set(regions))


def list_supported_models() -> list[dict]:
    return data.SUPPORTED_MODELS


def list_regions() -> dict[str, dict]:
    return data.REGIONS


def get_model(model_code: str) -> ModelNode | None:
    return _find(model_code)


def list_portfolio(segment: str | None = None, regions: list[str] | None = None) -> list[ModelNode]:
    return [
        _MODELS[i]
        for i in data.PORTFOLIO_IDS
        if (segment is None or _MODELS[i].segment == segment)
        and _in_regions(_MODELS[i].regions, regions)
    ]


def list_competitor_models(
    segment: str, regions: list[str], names: list[str] | None = None
) -> list[ModelNode]:
    out = [
        _MODELS[i]
        for i in data.COMPETITOR_IDS
        if _MODELS[i].segment == segment and _in_regions(_MODELS[i].regions, regions)
    ]
    if names:
        wanted = [n.lower() for n in names]
        out = [m for m in out if any(w in m.name.lower() for w in wanted)]
    return out


def get_attribute_values(
    model_id: str, attributes: list[str] | None = None
) -> list[AttributeValue]:
    model = _find(model_id)
    if model is None:
        raise KeyError(f"unknown model {model_id}")
    return [a for a in model.attributes if attributes is None or a.attribute in attributes]


def get_feedback_items(filters: FeedbackFilter) -> list[FeedbackItem]:
    items = [
        i
        for i in _FEEDBACK
        if (not filters.models or i.model in filters.models)
        and (not filters.markets or i.market in filters.markets)
        and (filters.since is None or (i.date and i.date >= filters.since))
    ]
    return items[: filters.limit] if filters.limit else items


def search_documents(
    query: str, kinds: list[str] | None = None, regions: list[str] | None = None, k: int = 10
) -> list[DocChunk]:
    terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    scored = []
    for kind, chunk in _DOCS:
        if (kinds and kind not in kinds) or not _in_regions(chunk.regions, regions):
            continue
        overlap = len(
            terms & set(re.findall(r"[a-z0-9]+", (chunk.doc_title + " " + chunk.text).lower()))
        )
        scored.append((overlap, chunk))
    scored.sort(key=lambda x: -x[0])
    return [c for s, c in scored if s > 0][:k] or [c for _, c in scored][:k]


def store_findings(analysis) -> None:
    stored_analyses.append(analysis)
