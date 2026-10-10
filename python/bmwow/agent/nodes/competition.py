"""competition_agent: what do competitors offer, at what values? (SPEC §6.2).

Fixed workflow, the LLM only reads pages:

1. competitors come from the brief (resolved per region, each tagged with the requested regions it is
   sold in); stored ontology values become findings first;
2. code picks the features to research (stale stored values, then the core features in rules.yaml)
   and writes one query per competitor x feature, searched in the locale of the competitor's region;
3. one LLM extraction per page returns values with verbatim quotes; code keeps a value only if the
   quote is on the page, the number is in the quote and the page is about that competitor;
4. a `Send` fan-out (internal subgraph) runs the competitors in parallel.

Only when the brief has no competitors does a bounded agent loop discover them on the web.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import Finding, Quantity, SearchLocale

from .. import router
from ..config import get_settings
from ..llm import get_chat_model
from ..prompting import render_prompt, render_regions
from ..rules import load_rules
from ..sources import Budget, attribute_source, clip, render_attribute
from ..tools.knowledge import AttributeValue, ModelNode
from ..tools.web_search import (
    WebPage,
    get_search_backend,
    make_web_tools,
    page_to_source,
    rank_chunks,
)
from ..validation import number_in_text
from .common import AgentContext, DraftFindings, run_tool_loop, structured_call

MAX_ATTRIBUTES_PER_COMPETITOR = 12
PAGE_CHARS = 3500


class ResearchTask(TypedDict):
    name: str
    regions: list[str]
    known: list[str]
    attributes: list[str]


class FanOutState(TypedDict, total=False):
    tasks: list[ResearchTask]
    done: Annotated[list[str], operator.add]


class ExtractedValue(BaseModel):
    feature: str = Field(description="one of the requested feature keys")
    found: bool = Field(
        description="false if the page does not state this feature for the competitor"
    )
    value: float | None = Field(description="the number exactly as written on the page, else null")
    unit: str | None = Field(
        description="unit as written, e.g. km, min, mm, EUR; null without value"
    )
    test_standard: str | None = Field(description="e.g. WLTP, EPA, 10-80%; null if not stated")
    region: str | None = Field(
        description="region or market the value applies to, if the page says"
    )
    variant: str | None = Field(description="trim / engine variant the value applies to, if stated")
    quote: str = Field(
        description="verbatim sentence from the page that states it; empty if not found"
    )


class ExtractionOutput(BaseModel):
    values: list[ExtractedValue]


@dataclass
class Competitor:
    name: str
    brand: str | None
    regions: list[str]


async def run(ctx: AgentContext) -> None:
    settings = get_settings()
    brief = ctx.brief
    errors_before = len(ctx.errors)
    ctx.kind_stats.update(n_from_ontology={"ontology"}, n_from_web={"web"})

    # 1. Competitors resolved for the requested regions; discover on the web only if there are none.
    models: list[ModelNode] = brief.competitors[: settings.max_competitors]
    tasks: list[ResearchTask] = []
    competitors: dict[str, Competitor] = {}
    if models:
        for m in models:
            try:
                values = m.attributes or (await router.fetch("attribute_values", m.node_id)).data
            except Exception as exc:  # noqa: BLE001 - stored values are optional
                ctx.mark(
                    f"competitor_values:{m.name}", "unavailable", f"{type(exc).__name__}: {exc}"
                )
                values = []
            for av in values:
                ctx.add(_ontology_finding(ctx, m, av))
            regions = m.regions or brief.regions
            competitors[m.name] = Competitor(m.name, m.brand, regions)
            tasks.append(_task(ctx, m.name, regions, values))
    else:
        ctx.mark(
            "competitors", "partial", "no competitors in the knowledge layer; discovered on the web"
        )
        for name, regions in (await _discover(ctx)).items():
            competitors[name] = Competitor(name, None, regions)
            tasks.append(_task(ctx, name, regions, []))
    ctx.stats["n_competitors"] = len(competitors)
    for region in brief.regions:
        ctx.stats[f"n_competitors:{region}"] = sum(
            region in c.regions for c in competitors.values()
        )

    # 2.-4. Fixed research workflow per competitor for missing / stale features.
    tasks = [t for t in tasks if t["attributes"]]
    if tasks:
        await _fan_out(ctx, tasks, competitors)

    ctx.findings = _dedupe(ctx.findings)
    ctx.stats["n_pages_scraped"] = ctx.budget.pages
    ctx.stats["n_tool_calls"] = ctx.budget.tool_calls
    ctx.stats["n_web_errors"] = len(ctx.errors) - errors_before


async def research_features(
    ctx: AgentContext, competitors: list[Competitor], features: list[str]
) -> None:
    """Targeted research of given features for given competitors (used by gap_fill)."""
    tasks = [
        ResearchTask(name=c.name, regions=c.regions, known=[], attributes=list(features))
        for c in competitors
    ]
    if tasks and features:
        await _fan_out(ctx, tasks, {c.name: c for c in competitors})
    ctx.findings = _dedupe(ctx.findings)


def _ontology_finding(ctx: AgentContext, model: ModelNode, av: AttributeValue) -> Finding:
    src = ctx.add_source(attribute_source(model, av))
    numeric = isinstance(av.value, (int, float)) and not isinstance(av.value, bool)
    unit = f" {av.unit}" if av.unit else ""
    note = f" ({av.source_note})" if av.source_note else ""
    prefix = "The source reports" if av.references else ""
    return ctx.finding(
        attribute=av.attribute,
        claim=f"{prefix} {model.name} has {av.attribute.replace('_', ' ')} of {av.value}{unit}{note}.",
        polarity="neutral",
        subject=model.name,
        source_ids=[src.id],
        confidence="high",
        quantity=Quantity(
            value=float(av.value), unit=av.unit or "", qualifier=av.source_note, origin="record"
        )
        if numeric and av.unit
        else None,
    )


def _task(
    ctx: AgentContext, name: str, regions: list[str], values: list[AttributeValue]
) -> ResearchTask:
    """Features to research: stored values that are stale (or undated web-sourced), then the core
    features of rules.yaml that the active taxonomy knows, else the focus attributes."""
    stale_before = date.today() - timedelta(days=get_settings().stale_after_days)
    fresh = {
        av.attribute
        for av in values
        if (av.as_of is None and not av.references)
        or (av.as_of is not None and av.as_of >= stale_before)
    }
    stale = [av.attribute for av in values if av.attribute not in fresh]
    core = [f for f in load_rules().competition.core_features if f in ctx.taxonomy.area_of]
    if not core:
        core = ctx.taxonomy.focus(ctx.brief.focus_areas)
    wanted = list(dict.fromkeys(a for a in stale + core if a not in fresh))
    return ResearchTask(
        name=name,
        regions=regions,
        known=[render_attribute(name, av) for av in values if av.attribute in fresh],
        attributes=wanted[:MAX_ATTRIBUTES_PER_COMPETITOR],
    )


def _locales(ctx: AgentContext, regions: list[str]) -> dict[str, SearchLocale]:
    return {r: ctx.brief.search_locale[r] for r in regions if r in ctx.brief.search_locale}


def _query_terms(ctx: AgentContext, feature: str) -> str:
    return load_rules().competition.core_features.get(feature) or feature.replace("_", " ")


def _about(page: WebPage, competitor: Competitor) -> bool:
    """The page must name the competitor (its brand when known, else its full name)."""
    text = f"{page.title}\n{page.markdown}".lower()
    marker = (competitor.brand or competitor.name).lower()
    return marker in text


async def _research(
    ctx: AgentContext, task: ResearchTask, competitor: Competitor, budget: Budget
) -> None:
    """Searches (one per feature, in priority order) and page extractions within the competitor's
    fixed share of the agent budget."""
    rules = load_rules().competition
    locale = next(iter(_locales(ctx, task["regions"]).values()), None)
    pages: dict[str, tuple[WebPage, list[str]]] = {}  # source id -> page, features it may hold
    for feature in task["attributes"]:
        if not budget.take("call"):
            ctx.mark(f"web:{competitor.name}", "partial", "search budget exhausted")
            break
        query = f"{competitor.name} {_query_terms(ctx, feature)}"
        try:
            found = await get_search_backend().search_pages(
                query, limit=rules.results_per_query, locale=locale
            )
        except Exception as exc:  # noqa: BLE001 - report, continue with the next feature
            ctx.errors.append(f"search {query!r}: {type(exc).__name__}: {exc}")
            continue
        kept = [p for p in found if _about(p, competitor)][: rules.pages_per_feature]
        for page in kept:
            source = ctx.add_source(page_to_source(page, query), full_text=page.markdown)
            pages.setdefault(source.id, (page, []))[1].append(feature)
    for sid, (page, features) in pages.items():
        if not budget.take("page"):
            ctx.mark(f"web:{competitor.name}", "partial", "page budget exhausted")
            break
        await _extract(ctx, competitor, sid, page, list(dict.fromkeys(features)))


async def _extract(
    ctx: AgentContext, competitor: Competitor, sid: str, page: WebPage, features: list[str]
) -> None:
    focus = " ".join(_query_terms(ctx, f) for f in features)
    body, used = [], 0
    for chunk in rank_chunks(page.markdown, focus):
        if used + len(chunk) > PAGE_CHARS:
            break
        body.append(chunk)
        used += len(chunk)
    prompt = render_prompt(
        "competition_extract",
        brief=ctx.brief,
        taxonomy=ctx.taxonomy,
        competitor=competitor.name,
        competitor_regions=render_regions(ctx.brief, competitor.regions),
        features="\n".join(f"- {f}: {_query_terms(ctx, f)}" for f in features),
        page=f"{page.title}\n\n" + "\n\n".join(body),
    )
    try:
        out = await structured_call(get_chat_model("cheap"), ExtractionOutput, prompt)
    except Exception as exc:  # noqa: BLE001 - one page failing must not stop the others
        ctx.errors.append(f"extract {competitor.name} {sid}: {type(exc).__name__}: {exc}")
        return
    rejected = 0
    for v in out.values:
        if not v.found or v.feature not in features or not ctx.registry.attach_quote(sid, v.quote):
            rejected += int(v.found)
            continue
        label = v.feature.replace("_", " ")
        region = (v.region or "").upper()
        region = region if region in competitor.regions else None
        quantity = None
        if v.value is not None and v.unit and number_in_text(v.value, v.quote, v.unit):
            qualifier = "; ".join(x for x in (v.test_standard, v.variant, region) if x)
            quantity = Quantity(
                value=v.value, unit=v.unit.strip(), qualifier=qualifier, origin="source_text"
            )
            claim = (
                f"{competitor.name} has {label} of {v.value:g} {v.unit.strip()}"
                f"{f' ({qualifier})' if qualifier else ''}."
            )
        else:
            rejected += int(v.value is not None)
            claim = f'{competitor.name}, {label}: "{clip(v.quote, 200)}"'
        ctx.add(
            ctx.finding(
                attribute=v.feature,
                claim=claim,
                polarity="neutral",
                subject=competitor.name,
                source_ids=[sid],
                confidence="medium",
                quantity=quantity,
                region=region,
            )
        )
    ctx.stats["n_rejected_extractions"] = int(ctx.stats.get("n_rejected_extractions", 0)) + rejected


async def _fan_out(
    ctx: AgentContext, tasks: list[ResearchTask], competitors: dict[str, Competitor]
) -> None:
    # Fixed shares, so parallel competitors cannot starve each other.
    calls = max(1, ctx.budget.max_tool_calls // len(tasks))
    pages = max(1, ctx.budget.max_pages // len(tasks))

    async def research(task: ResearchTask) -> dict[str, Any]:
        try:
            budget = ctx.budget.child(calls, pages)
            await _research(ctx, task, competitors[task["name"]], budget)
        except Exception as exc:  # noqa: BLE001 - one competitor failing must not stop the others
            ctx.errors.append(f"research {task['name']}: {type(exc).__name__}: {exc}")
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
        prompt = render_prompt(
            "competition_discover",
            brief=ctx.brief,
            taxonomy=ctx.taxonomy,
            region=render_regions(ctx.brief, [region]),
            max_competitors=settings.max_competitors,
            max_tool_calls=calls,
        )
        try:
            out = await run_tool_loop(
                get_chat_model("strong"),
                make_web_tools(ctx.registry, budget, ctx.errors, _locales(ctx, [region])),
                prompt,
                DraftFindings,
                calls,
            )
        except Exception as exc:  # one region failing must not stop the others
            ctx.errors.append(f"discover {region}: {type(exc).__name__}: {exc}")
            continue
        for draft in (out.findings if out else [])[: settings.max_competitors]:
            draft.attribute = "unmapped:competitive_set"
            finding = ctx.add_draft(
                draft, qualifier_suffix=region, claim_suffix=f"(region {region})"
            )
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
        q = (
            (f.quantity.value, f.quantity.unit.lower(), f.quantity.qualifier.lower())
            if f.quantity
            else (f.claim.lower(),)
        )
        key = (f.subject.lower(), f.attribute, q)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
