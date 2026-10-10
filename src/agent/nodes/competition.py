"""competition_agent: what do competitors offer, at what values? (AGENT_SPEC §6.2).

The competitor set comes from the brief (resolved per region, each competitor tagged with the requested
regions it is sold in). Ontology values first; then a `Send` fan-out (internal subgraph) runs one bounded
web tool loop per competitor, in the search locales of its regions, to fill focus attributes that are
missing or stale in the ontology.
"""

from __future__ import annotations

import operator
from datetime import date, timedelta
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.models.evidence import Finding, Quantity, SearchLocale

from .. import router
from ..config import get_settings
from ..llm import get_chat_model
from ..prompting import render_prompt, render_regions
from ..sources import attribute_source, render_attribute
from ..tools.knowledge import AttributeValue, ModelNode
from ..tools.web_search import make_web_tools
from .common import AgentContext, DraftFindings, run_tool_loop

MAX_ATTRIBUTES_PER_COMPETITOR = 12


class ResearchTask(TypedDict):
    name: str
    regions: list[str]
    known: list[str]
    attributes: list[str]


class FanOutState(TypedDict, total=False):
    tasks: list[ResearchTask]
    done: Annotated[list[str], operator.add]


async def run(ctx: AgentContext) -> None:
    settings = get_settings()
    brief = ctx.brief
    errors_before = len(ctx.errors)
    ctx.kind_stats.update(n_from_ontology={"ontology"}, n_from_web={"web"})

    # 1. Competitors resolved for the requested regions; discover on the web only if there are none.
    models: list[ModelNode] = brief.competitors[: settings.max_competitors]
    competitors: list[tuple[str, list[str], list[AttributeValue]]] = []
    if models:
        for m in models:
            values = m.attributes or (await router.fetch("attribute_values", m.node_id)).data
            competitors.append((m.name, m.regions or brief.regions, values))
            # 2. Ontology attribute values → findings.
            for av in values:
                ctx.add(_ontology_finding(ctx, m, av))
    else:
        competitors = [(name, regions, []) for name, regions in (await _discover(ctx)).items()]
    ctx.stats["n_competitors"] = len(competitors)
    for region in brief.regions:
        ctx.stats[f"n_competitors:{region}"] = sum(region in regions for _, regions, _ in competitors)

    # 3. Fan-out per competitor for missing / stale focus attributes.
    tasks = [t for t in (_task(ctx, name, regions, values) for name, regions, values in competitors)
             if t["attributes"]]
    if tasks:
        await _fan_out(ctx, tasks)

    # 4. Merge + dedupe by (subject, attribute, quantity).
    ctx.findings = _dedupe(ctx.findings)
    ctx.stats["n_pages_scraped"] = ctx.budget.pages
    ctx.stats["n_tool_calls"] = ctx.budget.tool_calls
    ctx.stats["n_web_errors"] = len(ctx.errors) - errors_before


def _ontology_finding(ctx: AgentContext, model: ModelNode, av: AttributeValue) -> Finding:
    src = ctx.add_source(attribute_source(model, av))
    numeric = isinstance(av.value, (int, float)) and not isinstance(av.value, bool)
    unit = f" {av.unit}" if av.unit else ""
    note = f" ({av.source_note})" if av.source_note else ""
    return ctx.finding(
        attribute=av.attribute,
        claim=f"{model.name} has {av.attribute.replace('_', ' ')} of {av.value}{unit}{note}.",
        polarity="neutral", subject=model.name, source_ids=[src.id], confidence="high",
        quantity=Quantity(value=float(av.value), unit=av.unit or "", qualifier=av.source_note, origin="record")
        if numeric and av.unit else None,
    )


def _task(ctx: AgentContext, name: str, regions: list[str], values: list[AttributeValue]) -> ResearchTask:
    stale_before = date.today() - timedelta(days=get_settings().stale_after_days)
    fresh = {av.attribute for av in values if av.as_of is None or av.as_of >= stale_before}
    wanted = [a for a in ctx.taxonomy.focus(ctx.brief.focus_areas) if a not in fresh]
    return ResearchTask(name=name, regions=regions,
                        known=[render_attribute(name, av) for av in values if av.attribute in fresh],
                        attributes=wanted[:MAX_ATTRIBUTES_PER_COMPETITOR])


def _locales(ctx: AgentContext, regions: list[str]) -> dict[str, SearchLocale]:
    return {r: ctx.brief.search_locale[r] for r in regions if r in ctx.brief.search_locale}


async def _fan_out(ctx: AgentContext, tasks: list[ResearchTask]) -> None:
    per_calls = max(3, ctx.budget.max_tool_calls // len(tasks))
    per_pages = max(1, ctx.budget.max_pages // len(tasks))

    async def research(task: ResearchTask) -> dict[str, Any]:
        budget = ctx.budget.child(per_calls, per_pages)
        prompt = render_prompt(
            "competition_research", brief=ctx.brief, taxonomy=ctx.taxonomy,
            competitor=task["name"], competitor_name=task["name"],
            competitor_regions=render_regions(ctx.brief, task["regions"]),
            known_values="\n".join(f"- {k}" for k in task["known"]) or "- none",
            attributes="\n".join(f"- {a}" for a in task["attributes"]), max_tool_calls=per_calls,
        )
        try:
            tools = make_web_tools(ctx.registry, budget, ctx.errors, _locales(ctx, task["regions"]))
            out = await run_tool_loop(get_chat_model("strong"), tools, prompt, DraftFindings, per_calls)
        except Exception as exc:  # one competitor failing must not stop the others
            ctx.errors.append(f"research {task['name']}: {type(exc).__name__}: {exc}")
            return {"done": [task["name"]]}
        for draft in (out.findings if out else []):
            ctx.add_draft(draft, subject=task["name"])
        return {"done": [task["name"]]}

    def dispatch(state: FanOutState) -> list[Send]:
        return [Send("research", t) for t in state["tasks"]]

    graph = StateGraph(FanOutState)
    graph.add_node("research", research)
    graph.add_conditional_edges(START, dispatch, ["research"])
    graph.add_edge("research", END)
    # checkpointer=False: the sub-runs close over in-memory registries and must not be checkpointed.
    await graph.compile(checkpointer=False).ainvoke({"tasks": tasks})


async def _discover(ctx: AgentContext) -> dict[str, list[str]]:
    """One bounded web step per region, in that region's locale. Returns competitor name -> regions."""
    settings = get_settings()
    regions = ctx.brief.regions
    calls = max(3, ctx.budget.max_tool_calls // (4 * len(regions)))
    pages = max(1, ctx.budget.max_pages // (4 * len(regions)))
    found: dict[str, list[str]] = {}
    for region in regions:
        budget = ctx.budget.child(calls, pages)
        prompt = render_prompt("competition_discover", brief=ctx.brief, taxonomy=ctx.taxonomy,
                               region=render_regions(ctx.brief, [region]),
                               max_competitors=settings.max_competitors, max_tool_calls=calls)
        try:
            out = await run_tool_loop(get_chat_model("strong"),
                                      make_web_tools(ctx.registry, budget, ctx.errors, _locales(ctx, [region])),
                                      prompt, DraftFindings, calls)
        except Exception as exc:  # one region failing must not stop the others
            ctx.errors.append(f"discover {region}: {type(exc).__name__}: {exc}")
            continue
        for draft in (out.findings if out else [])[: settings.max_competitors]:
            draft.attribute = "unmapped:competitive_set"
            finding = ctx.add_draft(draft, qualifier_suffix=region, claim_suffix=f"(region {region})")
            # Only research competitors whose identification is backed by a source we actually saw.
            if all(sid in ctx.registry for sid in finding.source_ids):
                found.setdefault(finding.subject, [])
                if region not in found[finding.subject]:
                    found[finding.subject].append(region)
    return dict(list(found.items())[: settings.max_competitors])


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[Any, ...]] = set()
    out: list[Finding] = []
    for f in findings:  # ontology findings come first and win
        q = (f.quantity.value, f.quantity.unit.lower(), f.quantity.qualifier.lower()) if f.quantity else (f.claim.lower(),)
        key = (f.subject.lower(), f.attribute, q)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
