"""Static data-need → tool table (AGENT_SPEC §6.0.8).

Agents ask for a data need, never for a concrete tool, so swapping a data source is a one-line change
in `ROUTES`.
"""

from __future__ import annotations

from typing import Any, Literal

from .tools import graph_rag, sql_rag

ToolName = Literal["sql_rag", "graph_rag", "web_search"]

ROUTES: dict[str, tuple[ToolName, str]] = {
    "model": ("graph_rag", "get_model"),  # reference model, competitor overrides
    "portfolio": ("graph_rag", "list_portfolio"),
    "sales_volume": ("sql_rag", "sales_volume"),
    "competitor_models": ("graph_rag", "list_competitor_models"),
    "attribute_values": ("graph_rag", "get_attribute_values"),
    "feedback_items": ("graph_rag", "get_feedback_items"),
    "studies": ("graph_rag", "search_documents"),
    # Served by agent loops through LangChain tools (tools/web_search.py), listed for completeness.
    "competitor_live_specs": ("web_search", "web_search"),
    "live_trends": ("web_search", "web_search"),
}

_MODULES = {"graph_rag": graph_rag, "sql_rag": sql_rag}


def route(need: str) -> ToolName:
    return ROUTES[need][0]


async def fetch(need: str, *args: Any, **kwargs: Any) -> graph_rag.Retrieved[Any]:
    tool, fn_name = ROUTES[need]
    if tool not in _MODULES:
        raise ValueError(
            f"data need {need!r} is served by an agent tool loop ({tool}), not fetch()"
        )
    return await getattr(_MODULES[tool], fn_name)(*args, **kwargs)
