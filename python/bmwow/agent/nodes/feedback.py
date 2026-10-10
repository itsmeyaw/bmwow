"""feedback_agent: what do customers and the public say, and how often? (SPEC §6.3).

Deterministic pipeline; the LLM only labels clusters. Counts and shares are computed by code. With several
regions, all items are clustered together and every theme also gets per-region findings (share of that
region's items), so a theme that is strong in only one region stays visible.
"""

from __future__ import annotations

import asyncio
from collections import Counter

from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import Confidence, Quantity

from .. import router
from ..config import get_settings
from ..llm import get_chat_model, get_embeddings
from ..prompting import render_prompt
from ..sources import feedback_source
from ..tools.feedback_stats import Cluster, FeedbackClustering, analyze_feedback
from ..tools.knowledge import FeedbackFilter, FeedbackItem
from .common import AgentContext, Polarity, structured_call

MAX_THEME_SOURCES = 8


class ClusterLabel(BaseModel):
    attribute: str = Field(description="taxonomy key or unmapped:<snake_case_name>")
    polarity: Polarity
    claim: str = Field(description="one sentence, no numbers")
    source_keys: list[str] = Field(
        description="keys T1, T2, ... of the supporting texts (at least one)"
    )
    confidence: Confidence


async def run(ctx: AgentContext) -> None:
    brief = ctx.brief
    filters = FeedbackFilter(
        models=[brief.model_code], markets=brief.markets, limit=get_settings().feedback_max_items
    )
    items = (await router.fetch("feedback_items", filters)).data
    ctx.stats["n_items"] = len(items)
    if not items:
        ctx.stats.update(n_after_dedupe=0, n_clusters=0, noise_share=0.0)
        return

    result = await analyze_feedback(items, get_embeddings())
    ctx.stats.update(
        n_after_dedupe=result.n_after_dedupe,
        n_clusters=len(result.clusters),
        noise_share=round(result.noise_share, 4),
    )
    _distribution_stats(ctx, result)

    semaphore = asyncio.Semaphore(get_settings().llm_concurrency)
    labels = await asyncio.gather(
        *(_label(ctx, result, c, semaphore) for c in result.clusters), return_exceptions=True
    )
    # Clusters that receive the same (attribute, polarity) label are one theme: merge them so the
    # theme's share is not split across findings. Largest cluster first, so its claim leads.
    themes: dict[tuple[str, str], list[tuple[Cluster, ClusterLabel]]] = {}
    for cluster, label in zip(result.clusters, labels, strict=True):
        if isinstance(label, BaseException):
            ctx.errors.append(
                f"labeling cluster {cluster.label} failed: {type(label).__name__}: {label}"
            )
            continue
        themes.setdefault((ctx.taxonomy.normalize(label.attribute), label.polarity), []).append(
            (cluster, label)
        )
    for group in themes.values():
        _add_theme_finding(ctx, result, group)
        if len(brief.regions) > 1:
            for region in brief.regions:
                _add_region_finding(ctx, result, group, region)
    ctx.stats["n_themes"] = len(themes)


async def _label(
    ctx: AgentContext, result: FeedbackClustering, cluster: Cluster, semaphore: asyncio.Semaphore
) -> ClusterLabel:
    texts = "\n".join(
        f"[T{i}] {result.items[idx].text}" for i, idx in enumerate(cluster.representatives, 1)
    )
    prompt = render_prompt("feedback_label", brief=ctx.brief, taxonomy=ctx.taxonomy, texts=texts)
    async with semaphore:
        return await structured_call(get_chat_model("cheap"), ClusterLabel, prompt)


def _cited_items(
    ctx: AgentContext, result: FeedbackClustering, cluster: Cluster, label: ClusterLabel
) -> list[FeedbackItem]:
    reps = {f"T{i}": result.items[idx] for i, idx in enumerate(cluster.representatives, 1)}
    cited = [reps[k.strip()] for k in label.source_keys if k.strip() in reps]
    if not cited:
        # Fall back to all representatives: the cluster itself is the evidence for the share.
        ctx.stats["labels_without_valid_keys"] = (
            int(ctx.stats.get("labels_without_valid_keys", 0)) + 1
        )
        cited = list(reps.values())
    return cited


def _add_theme_finding(
    ctx: AgentContext, result: FeedbackClustering, group: list[tuple[Cluster, ClusterLabel]]
) -> None:
    lead_cluster, lead = group[0]
    cited: list[FeedbackItem] = []
    for cluster, label in group:
        cited += [i for i in _cited_items(ctx, result, cluster, label) if i not in cited]
    source_ids = [ctx.add_source(feedback_source(item)).id for item in cited[:MAX_THEME_SOURCES]]
    size = sum(cluster.size for cluster, _ in group)
    share = size / result.n_after_dedupe
    clusters_note = f", {len(group)} clusters" if len(group) > 1 else ""
    clusters_note += f", {'+'.join(ctx.brief.regions)}"
    ctx.add(
        ctx.finding(
            attribute=lead.attribute,
            claim=lead.claim,
            polarity=lead.polarity,
            subject="customers",
            source_ids=source_ids,
            confidence=lead.confidence,
            quantity=Quantity(
                value=round(share, 4),
                unit="share",
                qualifier=f"{size} of {result.n_after_dedupe} deduplicated feedback items{clusters_note}",
                origin="computed",
            ),
            weight=share,
        ),
        llm_claim=lead.claim,
    )


def _add_region_finding(
    ctx: AgentContext,
    result: FeedbackClustering,
    group: list[tuple[Cluster, ClusterLabel]],
    region: str,
) -> None:
    """The theme's share among one region's deduplicated items, citing items from that region only."""
    in_region = {
        i for i, item in enumerate(result.items) if ctx.brief.region_of(item.market) == region
    }
    members = [i for cluster, _ in group for i in cluster.members if i in in_region]
    if not members:
        return
    _, lead = group[0]
    cited = [
        i
        for c, label in group
        for i in _cited_items(ctx, result, c, label)
        if ctx.brief.region_of(i.market) == region
    ]
    pool = cited + [result.items[i] for i in members if result.items[i] not in cited]
    source_ids = list(
        dict.fromkeys(ctx.add_source(feedback_source(item)).id for item in pool[:MAX_THEME_SOURCES])
    )
    share = len(members) / len(in_region)
    ctx.add(
        ctx.finding(
            attribute=lead.attribute,
            claim=f"{lead.claim.rstrip('.')} (region {region}).",
            polarity=lead.polarity,
            subject="customers",
            source_ids=source_ids,
            confidence=lead.confidence,
            quantity=Quantity(
                value=round(share, 4),
                unit="share",
                qualifier=f"{len(members)} of {len(in_region)} deduplicated feedback items in {region}",
                origin="computed",
            ),
            weight=share,
        ),
        llm_claim=lead.claim,
    )


def _distribution_stats(ctx: AgentContext, result: FeedbackClustering) -> None:
    n = result.n_after_dedupe
    regions = Counter(ctx.brief.region_of(item.market) or "unknown" for item in result.items)
    for region, count in regions.most_common():
        ctx.stats[f"region_share:{region}"] = round(count / n, 4)
    for field_name, prefix in (("market", "market_share"), ("channel", "channel_share")):
        values = [getattr(item, field_name) for item in result.items if getattr(item, field_name)]
        if not values:
            continue
        for value, count in Counter(values).most_common():
            ctx.stats[f"{prefix}:{value}"] = round(count / n, 4)
