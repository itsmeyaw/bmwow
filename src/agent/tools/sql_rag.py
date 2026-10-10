"""Relational contracts (§4.2) as source-producing functions."""

from __future__ import annotations

from src.models.evidence import Source

from ..sources import sql_source, utcnow
from .graph_rag import Retrieved
from .knowledge import SalesRow, get_backend

EXCERPT_ROW_LIMIT = 24


def render_rows(rows: list[SalesRow]) -> str:
    return "\n".join(
        f"{r.model} | {r.market} | {r.period} | {r.units} units"
        f" | status={r.status} | source_group={r.source_group or 'unknown'}"
        for r in rows
    )


def latest_rows(rows: list[SalesRow], per_market: int = 2) -> list[SalesRow]:
    """The newest `per_market` periods of each market (what the baseline findings rely on)."""
    out: list[SalesRow] = []
    for market in sorted({r.market for r in rows}):
        market_rows = sorted((r for r in rows if r.market == market), key=lambda r: r.period)
        out += market_rows[-per_market:]
    return out


async def sales_volume(
    models: list[str],
    markets: list[str] | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
) -> Retrieved[list[SalesRow]]:
    rows = await get_backend().sales_volume(models, markets, period_from, period_to)
    params = {
        "models": models,
        "markets": markets,
        "period_from": period_from,
        "period_to": period_to,
    }
    shown = rows if len(rows) <= EXCERPT_ROW_LIMIT else latest_rows(rows)
    header = "model | market | period | units"
    if shown is not rows:
        header += f"  (latest two periods per market; {len(rows)} rows total)"
    text = header + "\n" + render_rows(shown) if rows else "no rows"
    query_source = sql_source(
        "sales_volume", params, text, title=f"Sales volume: {', '.join(models)}"
    )
    query_source.references = [ref for row in rows for ref in row.references]
    row_sources = [
        Source(
            id=f"kg:{row.row_id}",
            kind="sql",
            ref=row.row_id,
            title=f"Sales observation: {row.model}",
            excerpt=render_rows([row]),
            retrieved_at=utcnow(),
            references=row.references,
            context=row.context,
            limitations=row.limitations,
            measurement=row.measurement,
            model_codes=row.model_codes,
        )
        for row in rows
        if row.row_id is not None
    ]
    return Retrieved(rows, [query_source, *row_sources])
