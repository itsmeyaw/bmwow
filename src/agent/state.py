"""Graph state and reducers (AGENT_SPEC §5.2)."""

from __future__ import annotations

from typing import Annotated, TypedDict

from src.models.evidence import AgentName, AgentReport, AnalysisRequest, ProductBrief, SituationAnalysis


def merge_dict(a: dict | None, b: dict | None) -> dict:
    """Parallel agents write different keys of `reports`; without a reducer LangGraph raises
    InvalidUpdateError."""
    return {**(a or {}), **(b or {})}


class AnalysisState(TypedDict, total=False):
    run_id: str
    request: AnalysisRequest
    brief: ProductBrief  # set by resolve_request, or given up front (PM-corrected brief_override)
    resolve_error: str | None
    reports: Annotated[dict[AgentName, AgentReport], merge_dict]  # each agent writes its own key
    analysis: SituationAnalysis
