"""trends_agent: which product and global trends matter? (AGENT_SPEC §6.4).

Knowledge-layer studies first, then one bounded tool loop (strong model) over stored documents and the
web. Each trend becomes findings on taxonomy attributes with a horizon.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .. import router
from ..llm import get_chat_model
from ..prompting import render_prompt
from ..tools.graph_rag import make_graph_tools, render_chunks
from ..tools.knowledge import DocChunk
from ..tools.web_search import make_web_tools
from .common import AgentContext, DraftFinding, run_tool_loop

MAX_CANDIDATES = 12


class TrendFinding(DraftFinding):
    horizon: Literal["now", "1-2y", "3y+"]


class Trend(BaseModel):
    name: str
    category: Literal["technology", "regulation", "market", "customer_behavior"]
    findings: list[TrendFinding] = Field(description="one or more findings on taxonomy attributes")


class TrendsOutput(BaseModel):
    trends: list[Trend]


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
        got = await router.fetch("studies", query, ["study", "report"], ctx.brief.regions, 5)
        for chunk in got.data:
            if chunk.node_id not in candidates and len(candidates) < MAX_CANDIDATES:
                candidates[chunk.node_id] = chunk
                ctx.add_source(
                    next(s for s in got.sources if s.ref == chunk.node_id), full_text=chunk.text
                )

    # 2. Bounded tool loop.
    calls = ctx.budget.max_tool_calls
    tools = make_graph_tools(ctx.registry, ctx.budget, ctx.brief.regions) + make_web_tools(
        ctx.registry, ctx.budget, ctx.errors, ctx.brief.search_locale
    )
    prompt = render_prompt(
        "trends_research",
        brief=ctx.brief,
        taxonomy=ctx.taxonomy,
        candidates=render_chunks(list(candidates.values())),
        max_tool_calls=calls,
    )
    out = await run_tool_loop(get_chat_model("strong"), tools, prompt, TrendsOutput, calls)

    # 3. Trends → findings on taxonomy attributes, horizon in the qualifier or the claim.
    trends = out.trends if out else []
    for trend in trends:
        for draft in trend.findings:
            if draft.value is not None and draft.unit:
                ctx.add_draft(draft, qualifier_suffix=f"horizon {draft.horizon}")
            else:
                ctx.add_draft(
                    draft, claim_suffix=f"(trend: {trend.name}; horizon: {draft.horizon})"
                )

    ctx.stats.update(
        n_trends=len(trends), n_pages_scraped=ctx.budget.pages, n_tool_calls=ctx.budget.tool_calls
    )
