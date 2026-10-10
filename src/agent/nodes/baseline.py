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
    subject: str = Field(
        description="model code or name of the model the finding is about, or 'portfolio'"
    )
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
        prefix = "The source reports" if av.references else "The reference model"
        ctx.add(
            ctx.finding(
                attribute=av.attribute,
                claim=f"{prefix} {code} ({reference.name}) with {av.attribute.replace('_', ' ')} "
                f"of {av.value}{unit}{note}.",
                polarity="neutral",
                subject=code,
                source_ids=[src.id],
                confidence="high",
                quantity=Quantity(
                    value=float(av.value),
                    unit=av.unit or "",
                    qualifier=av.source_note,
                    origin="record",
                )
                if numeric and av.unit
                else None,
            )
        )
    ctx.stats["n_attributes"] = len(reference.attributes)

    # 3. Portfolio in the requested regions (fetched before sales so the share can be computed).
    portfolio_got = await router.fetch("portfolio", brief.segment, brief.regions)
    portfolio = [
        m for m in portfolio_got.data if m.node_id != reference.node_id and _code(m) != code
    ]
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


def _sales_ids(rows: list[SalesRow], fallback: str) -> list[str]:
    return list(dict.fromkeys(f"kg:{row.row_id}" if row.row_id else fallback for row in rows))


def _model_specific(row: SalesRow, code: str) -> bool:
    return len(row.model_codes) <= 1 and row.model == code


def _region_rows(rows: list[SalesRow], region: str, countries: list[str]) -> list[SalesRow]:
    # Prefer the reported regional grain; do not add country rows to a regional total.
    regional = [row for row in rows if row.market == region]
    return regional or [row for row in rows if row.market in countries]


async def _sales_findings(ctx: AgentContext, portfolio: list[ModelNode]) -> None:
    brief = ctx.brief
    code = brief.model_code
    got = await router.fetch("sales_volume", [code], brief.markets)
    rows: list[SalesRow] = got.data
    for source in got.sources:
        ctx.add_source(source)
    fallback = got.sources[0].id
    if not rows:
        ctx.errors.append(f"no sales rows for {code} in {', '.join(brief.markets)}")
        return

    actual = [row for row in rows if row.status == "actual" and _model_specific(row, code)]
    ctx.stats["total_units"] = sum(row.units for row in actual)
    ctx.stats["n_future_sales_rows"] = sum(
        row.status in {"source_reported_future", "forecast"} for row in rows
    )
    ctx.stats["n_grouped_sales_rows"] = sum(len(row.model_codes) > 1 for row in rows)
    attr = "unmapped:sales_volume"
    for row in rows:
        if row in actual:
            continue
        subject = row.source_group or row.model
        scope = "combined group " if len(row.model_codes) > 1 else ""
        ctx.add(
            ctx.finding(
                attribute=attr,
                claim=f"The source reports {scope}{subject} volume of {row.units} units "
                f"for {row.market} in {row.period} (status: {row.status}).",
                polarity="neutral",
                subject=subject,
                source_ids=_sales_ids([row], fallback),
                confidence="high",
                quantity=Quantity(
                    value=row.units,
                    unit="units",
                    qualifier=f"{row.period} {row.market}; {row.status}; {scope}{subject}",
                    origin="record",
                ),
            )
        )
    if not actual:
        ctx.errors.append(
            "Historical model-specific sales are unavailable; group/future observations are retained."
        )
        return

    by_market: dict[str, list[SalesRow]] = defaultdict(list)
    for row in actual:
        by_market[row.market].append(row)
    for market, market_rows in sorted(by_market.items()):
        _volume_findings(ctx, market_rows, fallback, market)

    for region in brief.regions:
        regional = _region_rows(actual, region, brief.region_markets.get(region, []))
        if len({row.market for row in regional}) > 1:
            _volume_findings(ctx, regional, fallback, region)

    names = [_code(model) for model in portfolio]
    if not names:
        return
    port = await router.fetch("sales_volume", names, brief.markets)
    for source in port.sources:
        ctx.add_source(source)
    # Only comparable actuals can enter portfolio shares. Group totals cannot be allocated.
    port_rows = [row for row in port.data if row.status == "actual" and len(row.model_codes) <= 1]
    own_keys = {row.row_id for row in actual if row.row_id is not None}
    port_rows = [row for row in port_rows if row.row_id is None or row.row_id not in own_keys]
    latest = max(row.period for row in actual)
    total_latest = 0
    for region in brief.regions:
        countries = brief.region_markets.get(region, [])
        own_rows = _region_rows([row for row in actual if row.period == latest], region, countries)
        other_rows = _region_rows(
            [row for row in port_rows if row.period == latest], region, countries
        )
        own, other = sum(row.units for row in own_rows), sum(row.units for row in other_rows)
        if not own_rows or not other_rows or own + other == 0:
            continue
        total_latest += own + other
        share = own / (own + other)
        ctx.add(
            ctx.finding(
                attribute=attr,
                claim=f"{code} accounted for {share:.1%} of BMW {brief.segment} portfolio volume in {region} in {latest}.",
                polarity="neutral",
                subject=code,
                source_ids=list(
                    dict.fromkeys(
                        _sales_ids(own_rows, fallback) + _sales_ids(other_rows, port.sources[0].id)
                    )
                ),
                confidence="high",
                quantity=Quantity(
                    value=round(share, 4),
                    unit="share",
                    qualifier=f"{latest} {region}",
                    origin="computed",
                ),
            )
        )
    ctx.stats["portfolio_units_latest"] = total_latest


def _volume_findings(ctx: AgentContext, rows: list[SalesRow], fallback: str, scope: str) -> None:
    periods: dict[str, int] = defaultdict(int)
    for row in rows:
        periods[row.period] += row.units
    code = ctx.brief.model_code
    ordered = sorted(periods)
    latest = ordered[-1]
    latest_rows = [row for row in rows if row.period == latest]
    origin: Literal["record", "computed"] = "record" if len(latest_rows) == 1 else "computed"
    ctx.add(
        ctx.finding(
            attribute="unmapped:sales_volume",
            claim=f"{code} sold {periods[latest]} units in {scope} in {latest}.",
            polarity="neutral",
            subject=code,
            source_ids=_sales_ids(latest_rows, fallback),
            confidence="high",
            quantity=Quantity(
                value=periods[latest], unit="units", qualifier=f"{latest} {scope}", origin=origin
            ),
        )
    )
    if len(ordered) >= 2 and periods[ordered[-2]] > 0:
        prev = ordered[-2]
        change = (periods[latest] - periods[prev]) / periods[prev]
        compared = [row for row in rows if row.period in {prev, latest}]
        ctx.add(
            ctx.finding(
                attribute="unmapped:sales_volume",
                claim=f"{code} volume in {scope} changed by {change:+.1%} from {prev} to {latest}.",
                polarity="positive" if change > 0 else "negative" if change < 0 else "neutral",
                subject=code,
                source_ids=_sales_ids(compared, fallback),
                confidence="high",
                quantity=Quantity(
                    value=round(change, 4),
                    unit="share",
                    qualifier=f"{prev}->{latest} {scope}",
                    origin="computed",
                ),
            )
        )


async def _positioning(ctx: AgentContext, models: list[ModelNode]) -> None:
    """`models` = the reference model (P1) followed by the portfolio in the requested regions."""
    keys = {f"P{i}": model_source(m).id for i, m in enumerate(models, 1)}
    sources_text = "\n\n".join(
        f"[{key}]\n{ctx.registry.get(sid).excerpt}" for key, sid in keys.items()
    )  # type: ignore[union-attr]
    prompt = render_prompt(
        "baseline_positioning",
        brief=ctx.brief,
        taxonomy=ctx.taxonomy,
        sources=sources_text,
        max_findings=MAX_POSITIONING_FINDINGS,
    )
    try:
        out = await structured_call(get_chat_model("cheap"), PositioningOutput, prompt)
    except Exception as exc:  # the deterministic findings stand on their own
        ctx.errors.append(f"positioning LLM step failed: {type(exc).__name__}: {exc}")
        return
    for p in out.findings[:MAX_POSITIONING_FINDINGS]:
        # Unknown keys map to an id that cannot resolve, so the validator drops and counts the finding.
        source_ids = [keys.get(k.strip(), f"unknown:{k}") for k in p.source_keys]
        ctx.add(
            ctx.finding(
                attribute=p.attribute,
                claim=p.claim,
                polarity=p.polarity,
                subject=p.subject,
                source_ids=source_ids,
                confidence=p.confidence,
            ),
            llm_claim=p.claim,
        )
    ctx.stats["n_positioning_findings"] = len(out.findings[:MAX_POSITIONING_FINDINGS])
