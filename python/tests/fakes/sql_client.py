"""In-memory fake of bmwow/agent/knowledge_bridge/sql_client.py (§4.2)."""

from __future__ import annotations

from bmwow.agent.tools.knowledge import SalesRow

from . import data

# The invented 2023/2024 observations are explicitly historical, not unknown.
_ROWS = [row.model_copy(update={"status": "actual"}) for row in data.sales()]


def sales_volume(
    models: list[str],
    markets: list[str] | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
) -> list[SalesRow]:
    return [
        r
        for r in _ROWS
        if r.model in models
        and (not markets or r.market in markets)
        and (period_from is None or r.period >= period_from)
        and (period_to is None or r.period <= period_to)
    ]
