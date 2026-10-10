"""Analysis graph (SPEC §5): resolve the request, run the four agents in one superstep, validate their
reports, structure the evidence per feature, then build and persist the hand-off.

                            ┌─> baseline_agent ────┐
                            ├─> competition_agent ─┤
    START ─> resolve_request┼─> feedback_agent ────┼─> validate ─> structure_agent ─> candidate_agent ─┐
                  │         └─> trends_agent ──────┘                   ⇅ (max 1 round)                │
                  └─(resolve_error)─> END                            gap_fill                          │
                                                                                                       │
                       END <─ collect <─(done)─ gate_requirements ⟲ (PM actions, if pm_gate) <─────────┘

Without `pm_gate`, candidate_agent goes straight to collect (the candidates stay "proposed").
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from bmwow.agent.models.evidence import (
    AGENT_NAMES,
    AgentName,
    AgentReport,
    AnalysisRequest,
    EvidencePackage,
    FeatureAssessment,
    GateEvent,
    OntologyPersistence,
    ProductBrief,
    RequirementCandidate,
    SituationAnalysis,
)

from .candidates import build_candidates
from .config import get_settings
from .nodes import AGENT_RUNS, competition
from .nodes.candidate import word_all
from .nodes.common import AgentContext, AgentRun, agent_node
from .nodes.gate import after_gate, gate_requirements
from .nodes.structure import judge
from .registry import ResolveError
from .resolve import check_brief, resolve_request
from .rules import load_rules
from .sources import Budget, utcnow
from .state import AnalysisState
from .structure import assemble, gap_requests
from .taxonomy import load_taxonomy
from .tools.knowledge import get_backend
from .validation import merge_reports, validate_report

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


async def validate(state: AnalysisState) -> dict[str, Any]:
    """Deterministic fan-in: fill missing reports and validate every report once more."""
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
    return {"reports": final}


async def structure_agent(state: AnalysisState) -> dict[str, Any]:
    """One evidence package per feature (code), judged with a rubric (LLM) and guarded (code).

    Before the first judgment, important features without any competitor evidence go to gap_fill once;
    the packages are then assembled again and judged."""
    rules = load_rules()
    taxonomy = await load_taxonomy()
    packages = assemble(state["reports"], state["brief"], rules)
    if not state.get("gap_round"):
        gaps = gap_requests(packages, state["brief"], rules, set(taxonomy.area_of))
        if gaps:
            return {"evidence_packages": packages, "gap_requests": gaps}
    assessments = await judge(state["brief"], taxonomy, packages)
    return {"evidence_packages": packages, "feature_assessments": assessments, "gap_requests": []}


def after_structure(state: AnalysisState) -> str:
    if state.get("gap_requests") and not state.get("gap_round"):
        return "gap_fill"
    return "candidate_agent"


async def candidate_agent(state: AnalysisState) -> dict[str, Any]:
    """Requirement candidates from the judged features: built by code, worded by an LLM if allowed."""
    packages = state.get("evidence_packages") or []
    candidates = build_candidates(
        packages, state.get("feature_assessments") or [], state["brief"], load_rules()
    )
    worded = await word_all(state["brief"], await load_taxonomy(), candidates, packages)
    return {"requirement_candidates": worded}


async def gap_fill(state: AnalysisState) -> dict[str, Any]:
    """One targeted competition round for the requested features; merged into the competition report."""
    settings = get_settings()
    brief = state["brief"]
    features = state.get("gap_requests") or []
    base = state["reports"]["competition"]
    ctx = AgentContext(
        agent="competition",
        brief=brief,
        taxonomy=await load_taxonomy(),
        budget=Budget(settings.max_tool_calls_per_agent, settings.max_pages_scraped_per_agent),
    )
    competitors = [
        competition.Competitor(m.name, m.brand, m.regions or brief.regions)
        for m in brief.competitors[: settings.max_competitors]
    ]
    try:
        await asyncio.wait_for(
            competition.research_features(ctx, competitors, features),
            timeout=settings.agent_timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - the first-round evidence stands on its own
        log.exception("gap_fill failed for run %s", state.get("run_id"))
        ctx.errors.append(f"gap_fill: {type(exc).__name__}: {exc}")
        ctx.mark("gap_fill", "unavailable", f"{type(exc).__name__}: {exc}")
    else:
        ctx.mark("gap_fill", "ok", f"researched {', '.join(features)}")
    merged = merge_reports(base, ctx.build_report())
    return {"reports": {"competition": merged}, "gap_round": 1, "gap_requests": []}


async def collect(state: AnalysisState) -> dict[str, Any]:
    """Build and persist the hand-off. All four reports are always present; validation is idempotent,
    so collect also holds this guarantee when mounted or called without the validate node."""
    reports = (await validate(state))["reports"]
    analysis = SituationAnalysis(
        run_id=state["run_id"],
        request=state["request"],
        brief=state["brief"],
        reports=reports,
        created_at=utcnow(),
        evidence_packages=state.get("evidence_packages") or [],
        feature_assessments=state.get("feature_assessments") or [],
        requirement_candidates=state.get("requirement_candidates") or [],
        gate_log=state.get("gate_log") or [],
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


def checkpoint_serde() -> JsonPlusSerializer:
    """Checkpoint serializer that may only rebuild the graph's own state types (the PM gate resumes
    runs from checkpoints; LangGraph will block unregistered types)."""
    return JsonPlusSerializer(
        allowed_msgpack_modules=[
            AnalysisRequest,
            ProductBrief,
            AgentReport,
            EvidencePackage,
            FeatureAssessment,
            RequirementCandidate,
            GateEvent,
            SituationAnalysis,
        ]
    )


def build_builder(
    agents: Mapping[AgentName, AgentRun] | None = None, pm_gate: bool = False
) -> StateGraph:
    """`agents` overrides individual agent runs (tests, demos). `pm_gate` adds the interactive
    gate_requirements node, which needs a checkpointer to pause and resume."""
    runs = {**AGENT_RUNS, **(agents or {})}
    builder = StateGraph(AnalysisState)
    builder.add_node("resolve_request", resolve)
    builder.add_edge(START, "resolve_request")
    builder.add_conditional_edges(
        "resolve_request", after_resolve, [*AGENT_NODE_NAMES.values(), END]
    )
    for agent in AGENT_NAMES:
        builder.add_node(AGENT_NODE_NAMES[agent], agent_node(agent, runs[agent]))
    builder.add_node("validate", validate)
    builder.add_node("structure_agent", structure_agent)
    builder.add_node("collect", collect)
    builder.add_edge(list(AGENT_NODE_NAMES.values()), "validate")  # waits for all four
    builder.add_node("gap_fill", gap_fill)
    builder.add_edge("validate", "structure_agent")
    builder.add_node("candidate_agent", candidate_agent)
    builder.add_conditional_edges(
        "structure_agent", after_structure, ["gap_fill", "candidate_agent"]
    )
    builder.add_edge("gap_fill", "structure_agent")
    if pm_gate:
        builder.add_node("gate_requirements", gate_requirements)
        builder.add_edge("candidate_agent", "gate_requirements")
        builder.add_conditional_edges(
            "gate_requirements", after_gate, ["gate_requirements", "collect"]
        )
    else:
        builder.add_edge("candidate_agent", "collect")
    builder.add_edge("collect", END)
    return builder


def build_graph(
    checkpointer: Checkpointer = None,
    agents: Mapping[AgentName, AgentRun] | None = None,
    pm_gate: bool = False,
) -> CompiledStateGraph:
    return build_builder(agents, pm_gate).compile(
        checkpointer=checkpointer, name="situation_analysis"
    )


def build_subgraph() -> CompiledStateGraph:
    """The same graph for mounting as one node in the downstream pipeline (inherits its checkpointer).

    The parent state must provide `run_id` and `request` (optionally a ready `brief`); it receives
    `brief`, `resolve_error`, `reports`, `evidence_packages`, `feature_assessments` and `analysis`.
    """
    return build_builder().compile(name="situation_analysis")
