"""baseline_agent: where does our own product stand today? (SPEC §6.1, no web, no LLM).

Facts only, computed by code from the knowledge layer: catalog values of the reference model (with
standard / optional availability), sales per market and region (forecasts and combined groups kept as
reported), portfolio share, and customer-study scores mapped to features. A data source that is not
connected is reported as unavailable; the agent continues with the rest. Judgments (e.g. portfolio
overlaps) belong to structure_agent, which sees all four views.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from bmwow.agent.models.evidence import Quantity

from .. import router
from ..config import get_settings
from ..models.evidence import Source
from ..rules import (
    engine_type,
    feature_for_term,
    is_lower_better,
    load_study_mappings,
    powertrain_of,
)
from ..sources import attribute_source, model_source
from ..tools.knowledge import ModelNode, SalesRow, StudyScore
from .common import AgentContext


async def run(ctx: AgentContext) -> None:
    brief = ctx.brief
    reference = brief.reference_model
    code = brief.model_code

    # 1. Reference-model catalog values (loaded by resolve_request): one finding per value.
    ctx.add_source(model_source(reference))
    for av in reference.attributes:
        src = ctx.add_source(attribute_source(reference, av))
        numeric = isinstance(av.value, (int, float)) and not isinstance(av.value, bool)
        unit = f" {av.unit}" if av.unit else ""
        # Comparison key parts: the powertrain of the variant the catalog row names, and for a
        # configuration interval its best end (an interval is never averaged).
        variant = getattr(av, "variant", None)
        pt = (
            engine_type(av.context.engine_types if av.context else [])
            or powertrain_of(variant)
            or powertrain_of(av.source_note.split(";")[0])
        )
        best, span = (float(av.value) if numeric else None), ""
        if av.value_range is not None and av.unit:
            lo, hi = av.value_range.minimum, av.value_range.maximum
            best = lo if is_lower_better(av.attribute, av.unit) else hi
            span = f"best configuration of {lo:g}–{hi:g}"
        qualifier = "; ".join(
            x
            for x in (
                span,
                f"variant {variant}" if variant else "",
                f"powertrain {pt}" if pt else "",
            )
            if x
        )
        note = (
            f" ({av.source_note.split(';')[0]})" if av.source_note else ""
        )  # readable statement only
        offered = f", {av.availability}" if av.availability and av.availability != "unknown" else ""
        prefix = "The source reports" if av.references else "The reference model"
        ctx.add(
            ctx.finding(
                attribute=av.attribute,
                claim=f"{prefix} {code} ({reference.name}) with {av.attribute.replace('_', ' ')} "
                f"of {av.value}{unit}{note}{offered}.",
                polarity="neutral",
                subject=code,
                source_ids=[src.id],
                confidence="high",
                quantity=Quantity(
                    value=best,
                    unit=av.unit or "",
                    qualifier=qualifier or av.source_note,
                    origin="record",
                )
                if best is not None and av.unit
                else None,
                direction="neutral",
            )
        )
    ctx.stats["n_attributes"] = len(reference.attributes)
    ctx.mark(
        "catalog",
        "ok" if reference.attributes else "unavailable",
        "" if reference.attributes else f"no catalog values for {code}",
    )

    # 2. Portfolio in the requested regions (fetched before sales so the share can be computed).
    portfolio: list[ModelNode] = []
    try:
        portfolio_got = await router.fetch("portfolio", brief.segment, brief.regions)
        portfolio = [
            m for m in portfolio_got.data if m.node_id != reference.node_id and _code(m) != code
        ]
        ctx.mark("portfolio", "ok")
    except Exception as exc:  # noqa: BLE001 - missing data is reported, the run continues
        ctx.mark("portfolio", "unavailable", f"{type(exc).__name__}: {exc}")
    for model in portfolio:
        ctx.add_source(model_source(model))
    ctx.stats["n_portfolio_models"] = len(portfolio)

    # 3. Sales volume in the requested markets: computed findings.
    try:
        await _sales_findings(ctx, portfolio)
        ctx.mark("sales", "ok")
    except Exception as exc:  # noqa: BLE001
        ctx.mark("sales", "unavailable", f"{type(exc).__name__}: {exc}")

    # 4. Customer-study scores of the reference model, mapped to features.
    try:
        await _study_findings(ctx)
    except Exception as exc:  # noqa: BLE001
        ctx.mark("studies", "unavailable", f"{type(exc).__name__}: {exc}")


async def _study_findings(ctx: AgentContext) -> None:
    """One finding per study question and region. A mean is reported as is; a categorical answer
    distribution becomes one finding listing every category, with the share of the two top-listed
    categories (source row order) as its quantity. Scales are never harmonized across studies.
    The feature comes from the curated study mapping (proposed or reviewed), else from the aliases."""
    got = await router.fetch("study_scores", [ctx.brief.model_code], ctx.brief.regions)
    mappings = load_study_mappings(get_settings().curation_path)
    groups: dict[tuple[str, str, str, str], list[tuple[StudyScore, Source]]] = defaultdict(list)
    for score, source in zip(got.data, got.sources, strict=True):
        if score.value is not None:
            key = (score.study, score.region, score.question or "overall", score.statistic)
            groups[key].append((score, source))
    for (study, region, question, statistic), pairs in groups.items():
        mapping = mappings.get(question.strip().lower())
        feature = mapping.feature if mapping else feature_for_term(question)
        attribute = (
            feature
            if feature and feature in ctx.taxonomy.area_of
            else f"unmapped:study_{re.sub(r'[^a-z0-9]+', '_', question.lower()).strip('_')}"
        )
        how = f"; mapping {mapping.status}" if mapping and attribute == feature else ""
        source_ids = [ctx.add_source(source).id for _, source in pairs]
        score = pairs[0][0]
        model = score.model
        if score.response_category is None or len(pairs) == 1:
            unit = score.measurement.unit or ""
            category = f" answering {score.response_category!r}" if score.response_category else ""
            claim = (
                f"In {study} ({region}), {model} has a {statistic} of "
                f"{score.value:g}{(' ' + unit) if unit else ''}{category} on {question!r}."
            )
            quantity = Quantity(
                value=score.value,
                unit=unit or statistic,
                qualifier=f"{study}; {statistic}; {region}{how}",
                origin="record",
            )
        else:
            ordered = sorted(pairs, key=lambda pair: _row(pair[0]))
            top = ordered[-2:]
            share = round(sum(s.value or 0 for s, _ in top), 4)
            listed = ", ".join(f"{s.response_category} {s.value:.1%}" for s, _ in ordered)
            names = " + ".join(repr(s.response_category) for s, _ in top)
            claim = (
                f"In {study} ({region}), {share:.1%} of {model} answers on {question!r} fall in "
                f"the two top-listed categories {names} (distribution: {listed})."
            )
            quantity = Quantity(
                value=share,
                unit="share",
                qualifier=f"{study}; top-two listed categories; {region}{how}",
                origin="computed",
            )
        ctx.add(
            ctx.finding(
                attribute=attribute,
                claim=claim,
                polarity="neutral",
                subject=model,
                source_ids=source_ids,
                confidence="high",
                quantity=quantity,
                region=region,
                direction="neutral",
            )
        )
    ctx.stats["n_study_scores"] = len(got.data)
    ctx.stats["n_study_questions"] = len(groups)
    ctx.mark(
        "studies",
        "ok" if got.data else "unavailable",
        "" if got.data else "no study scores for the model in these regions",
    )


def _row(score: StudyScore) -> int:
    """Source row of a score's cell, which orders a categorical answer scale as the source lists it."""
    for ref in score.references:
        match = re.search(r"(\d+)$", getattr(ref.locator, "range", "") or "")
        if match:
            return int(match.group(1))
    return 0


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
    # The sales source reports regions (EU, US, CN) or countries; ask for both grains.
    markets = list(dict.fromkeys([*brief.regions, *brief.markets]))
    got = await router.fetch("sales_volume", [code], markets)
    rows: list[SalesRow] = got.data
    for source in got.sources:
        ctx.add_source(source)
    fallback = got.sources[0].id
    if not rows:
        ctx.errors.append(f"no sales rows for {code} in {', '.join(markets)}")
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
    port = await router.fetch("sales_volume", names, markets)
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
