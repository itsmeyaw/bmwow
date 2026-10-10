"""Analysis graph: resolve the request, fan-out to the four agents in one superstep, fan-in to `collect`
(AGENT_SPEC §5).

                            ┌─> baseline_agent ────┐
                            ├─> competition_agent ─┤
    START ─> resolve_request┼─> feedback_agent ────┼─> collect ─> END
                  │         └─> trends_agent ──────┘
                  └─(resolve_error)─> END
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from src.models.evidence import (
    AGENT_NAMES,
    AgentName,
    AgentReport,
    OntologyPersistence,
    SituationAnalysis,
)

from .config import get_settings
from .nodes import AGENT_RUNS
from .nodes.common import AgentRun, agent_node
from .registry import ResolveError
from .resolve import check_brief, resolve_request
from .sources import utcnow
from .state import AnalysisState
from .tools.knowledge import get_backend
from .validation import validate_report

log = logging.getLogger(__name__)

AGENT_NODE_NAMES: dict[AgentName, str] = {a: f"{a}_agent" for a in AGENT_NAMES}


async def resolve(state: AnalysisState) -> dict[str, Any]:
    """AnalysisRequest → ProductBrief. A PM-corrected brief given up front is checked, not re-resolved."""
    try:
        if state.get("brief") is not None:
            await check_brief(state["request"], state["brief"])
            return {"resolve_error": None}
        return {"brief": await resolve_request(state["request"]), "resolve_error": None}
    except ResolveError as exc:
        return {"resolve_error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - no agent runs without a brief; report instead of crashing
        log.exception("resolve_request failed for run %s", state.get("run_id"))
        return {"resolve_error": f"{type(exc).__name__}: {exc}"}


def after_resolve(state: AnalysisState) -> str | list[str]:
    if state.get("resolve_error"):
        return END
    return list(AGENT_NODE_NAMES.values())


async def collect(state: AnalysisState) -> dict[str, Any]:
    """Deterministic fan-in: fill missing reports, final validation, build and persist the hand-off."""
    reports = dict(state.get("reports") or {})
    final: dict[AgentName, AgentReport] = {}
    for agent in AGENT_NAMES:
        report = reports.get(agent)
        if report is None:
            report = AgentReport(
                agent=agent,
                status="failed",
                findings=[],
                sources=[],
                summary=f"{agent} agent produced no report.",
                errors=["no report produced"],
            )
        final[agent] = validate_report(report)
    analysis = SituationAnalysis(
        run_id=state["run_id"],
        request=state["request"],
        brief=state["brief"],
        reports=final,
        created_at=utcnow(),
    )
    analysis = await persist(analysis)
    return {"analysis": analysis}


async def persist(analysis: SituationAnalysis) -> SituationAnalysis:
    """Save locally before the optional write, then save its outcome; local write errors propagate."""
    out_dir = get_settings().analyses_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{analysis.run_id}.json"
    path.write_text(analysis.model_dump_json(indent=2))
    try:
        stored = await get_backend().store_findings(analysis)
        outcome = OntologyPersistence(status="stored" if stored else "skipped")
    except Exception as exc:  # optional write failure remains visible without losing the analysis
        log.exception("store_findings failed for run %s", analysis.run_id)
        outcome = OntologyPersistence(status="failed", error=f"{type(exc).__name__}: {exc}")
    persisted = analysis.model_copy(update={"ontology_persistence": outcome})
    # Replacing the file keeps the first saved analysis intact if the outcome update fails.
    temporary = NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=out_dir, prefix=f".{path.name}.", delete=False
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(persisted.model_dump_json(indent=2))
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return persisted


def build_builder(agents: Mapping[AgentName, AgentRun] | None = None) -> StateGraph:
    """`agents` overrides individual agent runs (tests, demos)."""
    runs = {**AGENT_RUNS, **(agents or {})}
    builder = StateGraph(AnalysisState)
    builder.add_node("resolve_request", resolve)
    builder.add_edge(START, "resolve_request")
    builder.add_conditional_edges(
        "resolve_request", after_resolve, [*AGENT_NODE_NAMES.values(), END]
    )
    for agent in AGENT_NAMES:
        builder.add_node(AGENT_NODE_NAMES[agent], agent_node(agent, runs[agent]))
    builder.add_node("collect", collect)
    builder.add_edge(list(AGENT_NODE_NAMES.values()), "collect")  # waits for all four
    builder.add_edge("collect", END)
    return builder


def build_graph(
    checkpointer: Checkpointer = None, agents: Mapping[AgentName, AgentRun] | None = None
) -> CompiledStateGraph:
    return build_builder(agents).compile(checkpointer=checkpointer, name="situation_analysis")


def build_subgraph() -> CompiledStateGraph:
    """The same graph for mounting as one node in the downstream pipeline (inherits its checkpointer).

    The parent state must provide `run_id` and `request` (optionally a ready `brief`); it receives
    `brief`, `resolve_error`, `reports` and `analysis`.
    """
    return build_builder().compile(name="situation_analysis")
