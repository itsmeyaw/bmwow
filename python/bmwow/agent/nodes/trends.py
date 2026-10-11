"""trends_agent: which product and global trends matter? (SPEC §6.4).

Knowledge-layer studies first, then one bounded tool loop (strong model) over stored documents and the
web. Each trend becomes findings on taxonomy attributes with a typed horizon and direction. Code counts
the independent sources behind each trend (distinct web domains and stored documents); a trend with a
single source is thin. Stored documents that are not connected are reported, the web loop still runs.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import Direction, TrendHorizon

from .. import router
from ..llm import get_chat_model
from ..prompting import render_prompt
from ..tools.graph_rag import make_graph_tools, render_chunks
from ..tools.knowledge import DocChunk
from ..tools.web_search import make_web_tools
from .common import AgentContext, DraftFinding, run_tool_loop

MAX_CANDIDATES = 12


class TrendFinding(DraftFinding):
    horizon: TrendHorizon


class Trend(BaseModel):
    name: str
    category: Literal["technology", "regulation", "market", "customer_behavior"]
    findings: list[TrendFinding] = Field(description="one or more findings on taxonomy attributes")


class TrendsOutput(BaseModel):
    trends: list[Trend]


_DIRECTION: dict[str, Direction] = {"demand": "request", "negative": "problem"}


def independent_sources(ctx: AgentContext, source_ids: list[str]) -> int:
    """Distinct web domains and distinct stored documents among the sources a trend cites."""
    keys: set[str] = set()
    for sid in source_ids:
        src = ctx.registry.get(sid)
        if src is None:
            continue
        if src.kind == "web":
            host = urlsplit(src.ref).netloc.lower().removeprefix("www.")
            keys.add(f"web:{host}")
        else:
            keys.add(f"doc:{src.title or src.ref}")
    return len(keys)


def _region(ctx: AgentContext, qualifier: str) -> str | None:
    found = [r for r in ctx.brief.regions if r in qualifier.split() or f" {r}" in f" {qualifier}"]
    return found[0] if len(found) == 1 else None


def brief_queries(ctx: AgentContext) -> list[str]:
    b = ctx.brief
    queries = [f"{b.segment} trends", f"{b.reference_model.name} customer expectations"]
    queries += [f"{area} trends {b.segment}" for area in b.focus_areas]
    queries += [f"regulation {region} {b.segment}" for region in b.regions]
    return queries


async def run(ctx: AgentContext) -> None:
    ctx.kind_stats.update(n_from_knowledge={"ontology"}, n_from_web={"web"})
    # 1. Candidate sources from the knowledge layer.
    candidates: dict[str, DocChunk] = {}
    for query in brief_queries(ctx):
        try:
            got = await router.fetch("studies", query, ["study", "report"], ctx.brief.regions, 5)
        except Exception as exc:  # noqa: BLE001 - missing data is reported, the web loop still runs
            ctx.mark("documents", "unavailable", f"{type(exc).__name__}: {exc}")
            break
        for chunk in got.data:
            if chunk.node_id not in candidates and len(candidates) < MAX_CANDIDATES:
                candidates[chunk.node_id] = chunk
                ctx.add_source(
                    next(s for s in got.sources if s.ref == chunk.node_id), full_text=chunk.text
                )

    # 2. Bounded tool loop.
    calls = ctx.budget.max_tool_calls
    documents_down = any(
        a.source == "documents" and a.status == "unavailable" for a in ctx.availability
    )
    tools = [] if documents_down else make_graph_tools(ctx.registry, ctx.budget, ctx.brief.regions)
    tools += make_web_tools(ctx.registry, ctx.budget, ctx.errors, ctx.brief.search_locale)
    prompt = render_prompt(
        "trends_research",
        brief=ctx.brief,
        taxonomy=ctx.taxonomy,
        candidates=render_chunks(list(candidates.values())),
        max_tool_calls=calls,
    )
    out = await run_tool_loop(get_chat_model("strong"), tools, prompt, TrendsOutput, calls)

    # 3. Trends → findings on taxonomy attributes, with horizon, direction, region and the number of
    #    independent sources (counted by code over the whole trend).
    trends = out.trends if out else []
    for trend in trends:
        n_sources = independent_sources(ctx, [sid for d in trend.findings for sid in d.source_ids])
        for draft in trend.findings:
            if draft.value is not None and draft.unit:
                finding = ctx.from_draft(draft, qualifier_suffix=f"horizon {draft.horizon}")
            else:
                finding = ctx.from_draft(
                    draft, claim_suffix=f"(trend: {trend.name}; horizon: {draft.horizon})"
                )
            finding = finding.model_copy(
                update={
                    "horizon": draft.horizon,
                    "direction": _DIRECTION.get(draft.polarity, "neutral"),
                    "region": _region(ctx, draft.qualifier),
                    "n_independent_sources": n_sources,
                }
            )
            ctx.add(finding, llm_claim=draft.claim)
    if candidates or "documents" not in {a.source for a in ctx.availability}:
        ctx.mark(
            "documents",
            "ok" if candidates else "unavailable",
            "" if candidates else "no stored studies or reports for these regions",
        )

    ctx.stats.update(
        n_trends=len(trends), n_pages_scraped=ctx.budget.pages, n_tool_calls=ctx.budget.tool_calls
    )
