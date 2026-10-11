"""feedback_agent: what do customers say about which feature exactly, and how often?

Every count, share, interval and test is computed by code from the feedback aspects:

1. each aspect of an item becomes a mention: feature (interim alias mapping, see rules.yaml), direction
   (problem / request / strength / neutral) and aspect term;
2. distinct items are counted per feature × direction × region, against the population that can
   experience the feature (e.g. range: BEV + PHEV owners only);
3. shares get a Wilson interval, a thin-sample flag and, with several regions, a test against the other
   regions;
4. sub-themes say what exactly customers mean: specific aspect terms are grouped by code; when most items
   only carry generic terms, an LLM groups a sample of their texts (only if ALLOW_LLM_ON_INTERNAL_DATA);
5. unclassified recurring topics are reported as candidate features.

Claims are written from templates, so no number in this report comes from an LLM.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import (
    CandidateFeature,
    Confidence,
    Direction,
    FindingStats,
    Polarity,
    Quantity,
    RegionTest,
    SubTheme,
)

from .. import router
from ..config import get_settings
from ..llm import get_chat_model
from ..prompting import render_prompt
from ..rules import feature_for_term, is_generic_term, load_rules
from ..sources import clip, feedback_source
from ..stats import is_thin, two_proportion_p, wilson_interval
from ..taxonomy import Taxonomy
from ..tools.feedback_stats import exact_dedupe, normalize_text
from ..tools.knowledge import FeedbackFilter, FeedbackItem
from .common import AgentContext, structured_call

ALL = "ALL"  # pseudo-region: all requested regions together
UNCLASSIFIED = "unclassified"
_POLARITY: dict[Direction, Polarity] = {
    "problem": "negative",
    "request": "demand",
    "strength": "positive",
    "neutral": "neutral",
}
_VERB: dict[Direction, str] = {
    "problem": "report a problem with",
    "request": "ask for more or better",
    "strength": "praise",
    "neutral": "mention",
}


@dataclass(frozen=True)
class Mention:
    item_id: str
    region: str
    attribute: str  # taxonomy key or unmapped:<area>
    direction: Direction
    term: str  # aspect term, the sub-theme key
    generic: bool
    quote: str | None  # aspect quote verified against the item text


class SubThemeGroup(BaseModel):
    name: str = Field(description="3-8 concrete words, no numbers")
    keys: list[str] = Field(description="keys T1, T2, ... of the texts in this sub-theme (>= 2)")


class SubThemeOutput(BaseModel):
    groups: list[SubThemeGroup]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "unknown"


def feature_label(attribute: str) -> str:
    return attribute.removeprefix("unmapped:").replace("_", " ")


def direction_of(feedback_type: str | None, issue_type: str | None) -> Direction:
    rules = load_rules().feedback
    if feedback_type and feedback_type in rules.direction_by_feedback_type:
        return rules.direction_by_feedback_type[feedback_type]
    if issue_type and issue_type in rules.direction_by_issue_type:
        return rules.direction_by_issue_type[issue_type]
    return "problem"


def resolve_feature(
    term: str | None, label: str | None, mapped: str | None, taxonomy: Taxonomy
) -> str | None:
    """Feature of a mention, in order: the knowledge layer's mapping (ontology / curated VFC
    mapping), then the interim alias in rules.yaml; only features of the active taxonomy count."""
    for candidate in (mapped, feature_for_term(term), feature_for_term(label)):
        if candidate and candidate in taxonomy.area_of:
            return candidate
    return None


def mentions_of(
    item: FeedbackItem, region: str, taxonomy: Taxonomy
) -> tuple[list[Mention], list[Mention]]:
    """(feature mentions, unclassified mentions) of one item. Uses the imported aspects; items
    without aspects fall back to their original VFC classifications."""
    found: list[Mention] = []
    unclassified: list[Mention] = []
    text = normalize_text(item.text)
    mapped = {
        normalize_text(c.vfc_category): c.attribute
        for c in item.classifications
        if c.vfc_category and c.attribute
    }
    for aspect in item.aspects:
        term = (aspect.aspect_term or aspect.aspect_label or aspect.vfc_category or "").strip()
        quote = aspect.quote if aspect.quote and normalize_text(aspect.quote) in text else None
        # The knowledge layer's term mapping (reviewed, or proposed when the curation opts in) wins.
        feature = resolve_feature(
            term,
            aspect.aspect_label,
            getattr(aspect, "attribute", None) or mapped.get(normalize_text(term)),
            taxonomy,
        )
        area = aspect.vfc_category or ""
        direction = direction_of(aspect.feedback_type, aspect.issue_type)
        if feature is None and area.lower() == UNCLASSIFIED:
            unclassified.append(
                Mention(
                    item.item_id, region, f"unmapped:{_slug(term)}", direction, term, True, quote
                )
            )
            continue
        attribute = feature or f"unmapped:{_slug(area or term)}"
        found.append(
            Mention(item.item_id, region, attribute, direction, term, is_generic_term(term), quote)
        )
    if item.aspects:
        return found, unclassified
    for c in item.classifications:
        term = (c.vfc_category or "").strip()
        if not term or term.lower() == "no_class_found":
            continue
        feature = resolve_feature(term, c.vfc_combined, c.attribute, taxonomy)
        direction = direction_of(c.feedback_type, c.vfc_issue)
        attribute = feature or f"unmapped:{_slug(term)}"
        found.append(
            Mention(item.item_id, region, attribute, direction, term, is_generic_term(term), None)
        )
    return found, unclassified


async def run(ctx: AgentContext) -> None:
    brief = ctx.brief
    settings = get_settings()
    filters = FeedbackFilter(
        models=[brief.model_code], markets=brief.markets, limit=settings.feedback_max_items
    )
    try:
        fetched = (await router.fetch("feedback_items", filters)).data
    except Exception as exc:  # noqa: BLE001 - missing data is reported, the run continues
        ctx.mark("feedback", "unavailable", f"{type(exc).__name__}: {exc}")
        return
    items = exact_dedupe(fetched)
    ctx.stats.update(n_items=len(fetched), n_after_dedupe=len(items))
    truncated = any(i.retrieval is not None and i.retrieval.truncated for i in fetched[:1])
    if not items:
        ctx.mark("feedback", "unavailable", f"no feedback items for {brief.model_code}")
        return
    ctx.mark(
        "feedback",
        "partial" if truncated else "ok",
        f"retrieval truncated at {len(fetched)} items" if truncated else "",
    )

    region_of = {i.item_id: brief.region_of(i.market) or "other" for i in items}
    by_id = {i.item_id: i for i in items}
    for region in brief.regions:
        n = sum(1 for r in region_of.values() if r == region)
        ctx.stats[f"n_items:{region}"] = n
        if n == 0:
            markets = ", ".join(brief.region_markets.get(region, [])) or "none"
            ctx.mark(f"feedback:{region}", "unavailable", f"no feedback items (markets: {markets})")

    mentions: list[Mention] = []
    unclassified: list[Mention] = []
    for item in items:
        found, other = mentions_of(item, region_of[item.item_id], ctx.taxonomy)
        mentions += found
        unclassified += other
    ctx.stats["n_mentions"] = len(mentions)
    ctx.stats["unclassified_item_share"] = round(
        len({m.item_id for m in unclassified}) / len(items), 4
    )

    _add_findings(ctx, items, mentions, region_of)
    await _add_sub_themes(ctx, items, mentions, region_of)
    _add_candidates(ctx, unclassified, by_id)


# ---------------------------------------------------------------- findings


def _population(
    ctx: AgentContext, attribute: str, items: list[FeedbackItem], region_of: dict[str, str]
) -> tuple[dict[str, set[str]], str]:
    """Item ids per region (and ALL) that can experience the feature, plus the population label."""
    denominator = load_rules().feedback.denominators.get(attribute)
    engines = {e.upper() for e in denominator.engine_types} if denominator else None
    pop: dict[str, set[str]] = defaultdict(set)
    for item in items:
        if engines is not None and (item.engine_type or "").upper() not in engines:
            continue
        region = region_of[item.item_id]
        if region in ctx.brief.regions:
            pop[region].add(item.item_id)
            pop[ALL].add(item.item_id)
    return pop, (f"{denominator.label} feedback items" if denominator else "feedback items")


def _add_findings(
    ctx: AgentContext,
    items: list[FeedbackItem],
    mentions: list[Mention],
    region_of: dict[str, str],
) -> None:
    rules = load_rules()
    by_id = {i.item_id: i for i in items}
    grouped: dict[tuple[str, Direction], list[Mention]] = defaultdict(list)
    for m in mentions:
        grouped[(m.attribute, m.direction)].append(m)

    scopes = list(ctx.brief.regions) + ([ALL] if len(ctx.brief.regions) > 1 else [])
    n_findings = 0
    for (attribute, direction), group in sorted(grouped.items()):
        population, label = _population(ctx, attribute, items, region_of)
        hits: dict[str, set[str]] = defaultdict(set)
        for m in group:
            if m.item_id in population[m.region]:
                hits[m.region].add(m.item_id)
                hits[ALL].add(m.item_id)
        for scope in scopes:
            k, n = len(hits[scope]), len(population[scope])
            if k < rules.feedback.min_k or n == 0:
                continue
            region_test = None
            if scope != ALL and len(ctx.brief.regions) > 1:
                others = [r for r in ctx.brief.regions if r != scope]
                ok = sum(len(hits[r]) for r in others)
                on = sum(len(population[r]) for r in others)
                p = two_proportion_p(k, n, ok, on)
                if p is not None and min(n, on) >= rules.thin.min_n:
                    region_test = RegionTest(
                        other="+".join(others), other_k=ok, other_n=on, p_value=round(p, 6)
                    )
            low, high = wilson_interval(k, n)
            thin = is_thin(k, n, rules.thin.min_n, rules.thin.min_k)
            where = "all requested regions" if scope == ALL else scope
            denominator_label = f"{label}, {where}"
            share = k / n
            source_ids = [
                ctx.add_source(feedback_source(by_id[i])).id
                for i in _representatives(
                    [m for m in group if m.item_id in hits[scope]],
                    rules.feedback.max_sources_per_finding,
                )
            ]
            confidence: Confidence = "high" if not thin else ("medium" if k >= 5 else "low")
            ctx.add(
                ctx.finding(
                    attribute=attribute,
                    claim=f"{share:.1%} of {label} in {where} ({k} of {n}) "
                    f"{_VERB[direction]} {feature_label(attribute)}.",
                    polarity=_POLARITY[direction],
                    subject="customers",
                    source_ids=source_ids,
                    confidence=confidence,
                    quantity=Quantity(
                        value=round(share, 4),
                        unit="share",
                        qualifier=f"{k} of {n} {denominator_label}",
                        origin="computed",
                    ),
                    weight=share,
                    region=None if scope == ALL else scope,
                    direction=direction,
                    stats=FindingStats(
                        k=k,
                        n=n,
                        denominator_label=denominator_label,
                        ci_low=round(low, 4),
                        ci_high=round(high, 4),
                        thin=thin,
                        region_test=region_test,
                    ),
                )
            )
            n_findings += 1
    ctx.stats["n_feature_findings"] = n_findings


def _representatives(group: list[Mention], limit: int) -> list[str]:
    """Deterministic, diverse evidence: round-robin over aspect terms (most frequent first), items
    with a verified quote first."""
    by_term: dict[str, list[Mention]] = defaultdict(list)
    for m in group:
        by_term[m.term].append(m)
    queues = [
        sorted(ms, key=lambda m: (m.quote is None, m.item_id))
        for _, ms in sorted(by_term.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    chosen: list[str] = []
    while len(chosen) < limit and any(queues):
        for queue in queues:
            while queue and queue[0].item_id in chosen:
                queue.pop(0)
            if queue and len(chosen) < limit:
                chosen.append(queue.pop(0).item_id)
    return chosen


# ---------------------------------------------------------------- sub-themes


async def _add_sub_themes(
    ctx: AgentContext,
    items: list[FeedbackItem],
    mentions: list[Mention],
    region_of: dict[str, str],
) -> None:
    """Sub-themes count against the same population as the findings, so a feature's sub-themes
    never come from owners who cannot experience it (e.g. ICE owners on range)."""
    rules = load_rules().feedback
    by_id = {i.item_id: i for i in items}
    grouped: dict[tuple[str, Direction], list[Mention]] = defaultdict(list)
    for m in mentions:
        if m.region in ctx.brief.regions:
            grouped[(m.attribute, m.direction)].append(m)
    populations: dict[str, set[str]] = {}
    for attribute, _ in grouped:
        if attribute not in populations:
            populations[attribute] = _population(ctx, attribute, items, region_of)[0][ALL]
    for key, group in grouped.items():
        grouped[key] = [m for m in group if m.item_id in populations[key[0]]]

    llm_jobs: list[tuple[str, Direction, list[str]]] = []
    for (attribute, direction), group in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        items_all = {m.item_id for m in group}
        if len(items_all) < rules.min_k:
            continue
        specific: dict[str, set[str]] = defaultdict(set)
        generic_items: set[str] = set()
        for m in group:
            (generic_items if m.generic else specific[m.term]).add(m.item_id)
        generic_only = generic_items - {i for ids in specific.values() for i in ids}
        for term, ids in sorted(specific.items(), key=lambda kv: (-len(kv[1]), kv[0]))[
            : rules.max_sub_themes
        ]:
            if len(ids) < rules.min_k:
                continue
            ctx.sub_themes.append(
                SubTheme(
                    attribute=attribute,
                    direction=direction,
                    name=term,
                    k=len(ids),
                    of=len(items_all),
                    method="aspect_term",
                    source_ids=[
                        ctx.add_source(feedback_source(by_id[i])).id
                        for i in _representatives([m for m in group if m.item_id in ids], 2)
                    ],
                )
            )
        if len(generic_only) / len(items_all) >= rules.generic_share_for_llm:
            llm_jobs.append((attribute, direction, sorted(generic_only)))

    if not llm_jobs:
        return
    if not get_settings().allow_llm_on_internal_data:
        ctx.mark(
            "feedback:sub_themes_llm",
            "unavailable",
            f"{len(llm_jobs)} feature(s) only carry generic aspect terms; grouping their texts needs "
            "an LLM, disabled until ALLOW_LLM_ON_INTERNAL_DATA=true",
        )
        return
    jobs = llm_jobs[: rules.max_llm_features]
    semaphore = asyncio.Semaphore(get_settings().llm_concurrency)
    results = await asyncio.gather(
        *(_llm_sub_themes(ctx, a, d, ids, by_id, semaphore) for a, d, ids in jobs),
        return_exceptions=True,
    )
    for (attribute, _, _), result in zip(jobs, results, strict=True):
        if isinstance(result, BaseException):
            ctx.errors.append(f"sub-themes for {attribute}: {type(result).__name__}: {result}")
        else:
            ctx.sub_themes += result
    ctx.stats["n_llm_sub_theme_features"] = len(jobs)


async def _llm_sub_themes(
    ctx: AgentContext,
    attribute: str,
    direction: Direction,
    item_ids: list[str],
    by_id: dict[str, FeedbackItem],
    semaphore: asyncio.Semaphore,
) -> list[SubTheme]:
    rules = load_rules().feedback
    sample = item_ids[: rules.llm_sample_size]  # sorted ids: deterministic sample
    keys = {f"T{i}": item_id for i, item_id in enumerate(sample, 1)}
    texts = "\n".join(f"[{key}] {clip(by_id[i].text, 400)}" for key, i in keys.items())
    prompt = render_prompt(
        "feedback_subthemes",
        brief=ctx.brief,
        taxonomy=ctx.taxonomy,
        feature=feature_label(attribute),
        direction=direction,
        max_groups=rules.max_sub_themes,
        texts=texts,
    )
    async with semaphore:
        out = await structured_call(get_chat_model("cheap"), SubThemeOutput, prompt)
    themes: list[SubTheme] = []
    used: set[str] = set()
    for group in out.groups[: rules.max_sub_themes]:
        ids = [keys[k.strip()] for k in group.keys if k.strip() in keys and k.strip() not in used]
        used |= {k.strip() for k in group.keys}
        name = re.sub(r"\d", "", group.name).strip()  # names carry no numbers; code counts
        if len(set(ids)) < 2 or not name:
            continue
        themes.append(
            SubTheme(
                attribute=attribute,
                direction=direction,
                name=name,
                k=len(set(ids)),
                of=len(sample),
                method="llm",
                source_ids=[ctx.add_source(feedback_source(by_id[i])).id for i in ids[:2]],
            )
        )
    return themes


# ---------------------------------------------------------------- open signals


def _add_candidates(
    ctx: AgentContext, unclassified: list[Mention], by_id: dict[str, FeedbackItem]
) -> None:
    rules = load_rules().feedback
    by_term: dict[str, set[str]] = defaultdict(set)
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for m in unclassified:
        if m.region not in ctx.brief.regions or is_generic_term(m.term):
            continue  # "overall car" and the like are not a new feature
        key = normalize_text(m.term)
        by_term[key].add(m.item_id)
        names[key][m.term] += 1
    ranked = sorted(by_term.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for key, ids in ranked[: rules.max_candidates]:
        if len(ids) < rules.candidate_min_k:
            continue
        ctx.candidates.append(
            CandidateFeature(
                name=names[key].most_common(1)[0][0],
                k=len(ids),
                n=len(by_id),
                source_ids=[ctx.add_source(feedback_source(by_id[i])).id for i in sorted(ids)[:2]],
            )
        )
