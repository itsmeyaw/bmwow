"""Graph state and reducers (SPEC §5.2)."""

from __future__ import annotations

from typing import Annotated, TypedDict

from bmwow.agent.models.evidence import (
    AgentName,
    AgentReport,
    AnalysisRequest,
    EvidencePackage,
    FeatureAssessment,
    GateEvent,
    ProductBrief,
    RequirementCandidate,
    SituationAnalysis,
)


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
    evidence_packages: list[EvidencePackage]  # structure_agent: one per feature
    feature_assessments: list[FeatureAssessment]
    gap_requests: list[str]  # features to research once more before the judgment
    gap_round: int  # 0 before gap_fill, 1 after (one round at most)
    requirement_candidates: list[RequirementCandidate]  # candidate_agent, updated at the PM gate
    pending_constraints: list[dict]  # parsed from PM free text, waiting for confirm/cancel
    gate_log: list[GateEvent]
    gate_done: bool
    analysis: SituationAnalysis
