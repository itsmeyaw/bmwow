"""baseline_agent: where does our own product stand today? (AGENT_SPEC §6.1, no web)."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from src.models.evidence import Confidence, Quantity

from .. import router
from ..llm import get_chat_model
from ..prompting import render_prompt
from ..sources import attribute_source, model_source
from ..tools.knowledge import ModelNode, SalesRow
from .common import AgentContext, Polarity, structured_call

MAX_POSITIONING_FINDINGS = 8


class PositioningFinding(BaseModel):
    attribute: str = Field(description="taxonomy key or unmapped:<snake_case_name>")
    claim: str = Field(description="one sentence, one claim")
    polarity: Polarity
    subject: str = Field(description="model code or name of the model the finding is about, or 'portfolio'")
    source_keys: list[str] = Field(description="keys P1, P2, ... (at least one)")
    confidence: Confidence


class PositioningOutput(BaseModel):
    findings: list[PositioningFinding]


async def run(ctx: AgentContext) -> None:
    brief = ctx.brief
    reference = brief.reference_model
    code = brief.model_code

    # 1. Reference-model attribute values (loaded by resolve_request): one finding per value, no LLM.
    ctx.add_source(model_source(reference))
    for av in reference.attributes:
        src = ctx.add_source(attribute_source(reference, av))
        numeric = isinstance(av.value, (int, float)) and not isinstance(av.value, bool)
        unit = f" {av.unit}" if av.unit else ""
        note = f" ({av.source_note})" if av.source_note else ""
        ctx.add(ctx.finding(
            attribute=av.attribute,
            claim=f"The reference model {code} ({reference.name}) has {av.attribute.replace('_', ' ')} "
                  f"of {av.value}{unit}{note}.",
            polarity="neutral", subject=code, source_ids=[src.id], confidence="high",
            quantity=Quantity(value=float(av.value), unit=av.unit or "", qualifier=av.source_note, origin="record")
            if numeric and av.unit else None,
        ))
    ctx.stats["n_attributes"] = len(reference.attributes)

    # 3. Portfolio in the requested regions (fetched before sales so the share can be computed).
    portfolio_got = await router.fetch("portfolio", brief.segment, brief.regions)
    portfolio = [m for m in portfolio_got.data if m.node_id != reference.node_id and _code(m) != code]
    for model in portfolio:
        ctx.add_source(model_source(model))
    ctx.stats["n_portfolio_models"] = len(portfolio)

    # 2. Sales volume in the requested markets: computed findings.
    await _sales_findings(ctx, portfolio)

    # 4. LLM: positioning findings citing portfolio sources only.
    if portfolio:
        await _positioning(ctx, [reference, *portfolio])


def _code(model: ModelNode) -> str:
    """The key sales data uses for a model: its registry code when it has one, else its name."""
    return model.model_code or model.name


async def _sales_findings(ctx: AgentContext, portfolio: list[ModelNode]) -> None:
    brief = ctx.brief
    code = brief.model_code
    got = await router.fetch("sales_volume", [code], brief.markets)
    rows: list[SalesRow] = got.data
    src = ctx.add_source(got.sources[0])
    ctx.stats["total_units"] = sum(r.units for r in rows)
    if not rows:
        ctx.errors.append(f"no sales rows for {code} in {', '.join(brief.markets)}")
        return

    attr = "unmapped:sales_volume"
    by_market: dict[str, dict[str, int]] = defaultdict(dict)
    n_rows: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        by_market[r.market][r.period] = by_market[r.market].get(r.period, 0) + r.units
        n_rows[(r.market, r.period)] += 1
    for market, periods in sorted(by_market.items()):
        exact = all(n_rows[(market, p)] == 1 for p in periods)
        _volume_findings(ctx, src.id, market, periods, "record" if exact else "computed")

    # Per region: sum over the region's markets (only adds information when a region has several).
    for region in brief.regions:
        markets = [m for m in brief.region_markets.get(region, []) if m in by_market]
        if len(markets) < 2:
            continue
        periods: dict[str, int] = defaultdict(int)
        for m in markets:
            for period, units in by_market[m].items():
                periods[period] += units
        _volume_findings(ctx, src.id, region, dict(periods), "computed")

    # Share of portfolio volume per region, in the latest period of the reference model's data.
    names = [_code(m) for m in portfolio]
    if not names:
        return
    port = await router.fetch("sales_volume", names, brief.markets)
    port_rows: list[SalesRow] = port.data
    port_src = ctx.add_source(port.sources[0])
    latest = max(r.period for r in rows)
    total_latest = 0
    for region in brief.regions:
        markets = set(brief.region_markets.get(region, []))
        own = sum(r.units for r in rows if r.period == latest and r.market in markets)
        other = sum(r.units for r in port_rows if r.period == latest and r.market in markets)
        total_latest += own + other
        if own + other == 0:
            continue
        share = own / (own + other)
        ctx.add(ctx.finding(
            attribute=attr,
            claim=f"{code} accounted for {share:.1%} of BMW {brief.segment} portfolio volume in {region} in {latest}.",
            polarity="neutral", subject=code, source_ids=[src.id, port_src.id], confidence="high",
            quantity=Quantity(value=round(share, 4), unit="share", qualifier=f"{latest} {region}", origin="computed"),
        ))
    ctx.stats["portfolio_units_latest"] = total_latest


def _volume_findings(ctx: AgentContext, source_id: str, scope: str, periods: dict[str, int],
                     origin: Literal["record", "computed"]) -> None:
    """Latest volume and period-over-period change for one market or region."""
    code = ctx.brief.model_code
    attr = "unmapped:sales_volume"
    ordered = sorted(periods)
    latest = ordered[-1]
    ctx.add(ctx.finding(
        attribute=attr, claim=f"{code} sold {periods[latest]} units in {scope} in {latest}.",
        polarity="neutral", subject=code, source_ids=[source_id], confidence="high",
        quantity=Quantity(value=periods[latest], unit="units", qualifier=f"{latest} {scope}", origin=origin),
    ))
    if len(ordered) >= 2 and periods[ordered[-2]] > 0:
        prev = ordered[-2]
        change = (periods[latest] - periods[prev]) / periods[prev]
        ctx.add(ctx.finding(
            attribute=attr,
            claim=f"{code} volume in {scope} changed by {change:+.1%} from {prev} to {latest}.",
            polarity="positive" if change > 0 else "negative" if change < 0 else "neutral",
            subject=code, source_ids=[source_id], confidence="high",
            quantity=Quantity(value=round(change, 4), unit="share", qualifier=f"{prev}->{latest} {scope}",
                              origin="computed"),
        ))


async def _positioning(ctx: AgentContext, models: list[ModelNode]) -> None:
    """`models` = the reference model (P1) followed by the portfolio in the requested regions."""
    keys = {f"P{i}": model_source(m).id for i, m in enumerate(models, 1)}
    sources_text = "\n\n".join(f"[{key}]\n{ctx.registry.get(sid).excerpt}" for key, sid in keys.items())  # type: ignore[union-attr]
    prompt = render_prompt("baseline_positioning", brief=ctx.brief, taxonomy=ctx.taxonomy,
                           sources=sources_text, max_findings=MAX_POSITIONING_FINDINGS)
    try:
        out = await structured_call(get_chat_model("cheap"), PositioningOutput, prompt)
    except Exception as exc:  # the deterministic findings stand on their own
        ctx.errors.append(f"positioning LLM step failed: {type(exc).__name__}: {exc}")
        return
    for p in out.findings[:MAX_POSITIONING_FINDINGS]:
        # Unknown keys map to an id that cannot resolve, so the validator drops and counts the finding.
        source_ids = [keys.get(k.strip(), f"unknown:{k}") for k in p.source_keys]
        ctx.add(ctx.finding(attribute=p.attribute, claim=p.claim, polarity=p.polarity, subject=p.subject,
                            source_ids=source_ids, confidence=p.confidence), llm_claim=p.claim)
    ctx.stats["n_positioning_findings"] = len(out.findings[:MAX_POSITIONING_FINDINGS])
