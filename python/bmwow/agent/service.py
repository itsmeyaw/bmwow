"""Public entry points for the analysis API (SPEC §7)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.types import Command
from pydantic import BaseModel

from bmwow.agent.models.evidence import (
    AGENT_NAMES,
    AgentName,
    AnalysisRequest,
    OntologyPersistence,
    ProductBrief,
    SituationAnalysis,
    Source,
    SupportedModel,
)

from .config import get_settings
from .explain import EXPLAIN_TOP_K, Explanation, answer_from_evidence, retrieve
from .registry import ResolveError, load_registry
from .resolve import check_brief, resolve_request
from .sources import utcnow
from .supervisor import AGENT_NODE_NAMES, build_graph, checkpoint_serde

log = logging.getLogger(__name__)

AgentRunState = Literal["pending", "running", "ok", "partial", "failed"]
_NODE_TO_AGENT = {node: agent for agent, node in AGENT_NODE_NAMES.items()}


RunState = Literal["running", "waiting_for_pm", "done", "failed"]


class RunStatus(BaseModel):
    run_id: str
    state: RunState  # waiting_for_pm: paused at gate_requirements, see `gate`
    agents: dict[AgentName, AgentRunState]
    analysis: SituationAnalysis | None = None
    error: str | None = (
        None  # optional addition: why the run failed (e.g. the request did not resolve)
    )
    brief: ProductBrief | None = None  # optional addition: the resolved brief, as soon as it exists
    ontology_persistence: OntologyPersistence | None = None
    # While waiting_for_pm: the candidates, pending constraints, the last response and the actions.
    gate: dict[str, Any] | None = None


# ---------------------------------------------------------------- run registry


@dataclass
class _Run:
    run_id: str
    state: RunState = "running"
    agents: dict[AgentName, AgentRunState] = field(
        default_factory=lambda: {a: "pending" for a in AGENT_NAMES}
    )
    analysis: SituationAnalysis | None = None
    error: str | None = None
    brief: ProductBrief | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None
    pm_gate: bool = False
    gate: dict[str, Any] | None = None

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append({"run_id": self.run_id, "ts": utcnow().isoformat(), **event})
        async with self.changed:
            self.changed.notify_all()

    def status(self) -> RunStatus:
        return RunStatus(
            run_id=self.run_id,
            state=self.state,
            agents=dict(self.agents),
            analysis=self.analysis,
            error=self.error,
            brief=self.brief,
            ontology_persistence=self.analysis.ontology_persistence if self.analysis else None,
            gate=self.gate if self.state == "waiting_for_pm" else None,
        )


_runs: dict[str, _Run] = {}
# (id(loop), pm_gate) -> (graph, sqlite connection)
_graph_cache: dict[tuple[int, bool], tuple[Any, Any]] = {}


async def _get_graph(pm_gate: bool = False) -> Any:
    """Compiled graph with the SQLite checkpointer, one per event loop (aiosqlite is loop-bound) and
    gate mode."""
    loop = asyncio.get_running_loop()
    cached = _graph_cache.get((id(loop), pm_gate))
    if cached is not None:
        return cached[0]
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = get_settings().checkpoint_db
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(path))
    graph = build_graph(
        checkpointer=AsyncSqliteSaver(conn, serde=checkpoint_serde()), pm_gate=pm_gate
    )
    _graph_cache[(id(loop), pm_gate)] = (graph, conn)
    return graph


async def aclose() -> None:
    """Cancel running analyses and close the checkpointer connection (call on API shutdown)."""
    for run in _runs.values():
        if run.task is not None and not run.task.done():
            run.task.cancel()
    loop = id(asyncio.get_running_loop())
    for key in [k for k in _graph_cache if k[0] == loop]:
        await _graph_cache.pop(key)[1].close()


# ---------------------------------------------------------------- request → brief


async def list_models() -> list[SupportedModel]:
    """Model registry entries (§4.5) for the UI dropdowns: model_code, name, regions."""
    return list((await load_registry()).models.values())


async def resolve(request: AnalysisRequest) -> ProductBrief:
    """Dry run of resolve_request, so the UI can show (and the PM correct) the brief before launching.

    Raises `ResolveError` (a ValueError) for an unknown model code or region, or an unsupported
    model–region combination; the message lists the valid choices.
    """
    return await resolve_request(request)


async def start_analysis(
    request: AnalysisRequest, brief_override: ProductBrief | None = None, pm_gate: bool = False
) -> str:
    """Create a run id, launch the graph in the background and return immediately.

    `brief_override` = the PM-corrected brief from `resolve()`, used instead of re-resolving. Registry
    checks run before launching, so invalid input raises `ResolveError` here instead of a failed run.
    With `pm_gate`, the run pauses at gate_requirements (state `waiting_for_pm`); continue it with
    `gate_action`.
    """
    registry = await load_registry()
    registry.check(request)
    if brief_override is not None:
        await check_brief(request, brief_override, registry)
    run_id = uuid.uuid4().hex[:12]
    run = _Run(run_id=run_id, brief=brief_override, pm_gate=pm_gate)
    _runs[run_id] = run
    run.task = asyncio.create_task(
        _execute(run, request, brief_override), name=f"analysis-{run_id}"
    )
    return run_id


async def _execute(run: _Run, request: AnalysisRequest, brief: ProductBrief | None) -> None:
    await run.emit({"event": "run_started"})
    inputs: dict[str, Any] = {"run_id": run.run_id, "request": request}
    if brief is not None:
        inputs["brief"] = brief
    await _drive(run, inputs)


async def gate_action(run_id: str, action: dict[str, Any]) -> RunStatus:
    """Send one PM action to a run waiting at gate_requirements; returns once the run pauses again
    (with the response in `gate["last"]`) or finishes after {"action": "done"}."""
    run = _runs.get(run_id)
    if run is None:
        raise KeyError(f"unknown run_id {run_id}")
    if run.state != "waiting_for_pm":
        raise ValueError(f"run {run_id} is {run.state}, not waiting for the PM")
    run.state = "running"
    await run.emit({"event": "gate_action", "action": action})
    await _drive(run, Command(resume=action))
    return run.status()


async def _drive(run: _Run, graph_input: Any) -> None:
    """Run the graph until it finishes, fails or pauses at the PM gate."""
    try:
        graph = await _get_graph(run.pm_gate)
        config = {"configurable": {"thread_id": run.run_id}}
        async for mode, chunk in graph.astream(
            graph_input, config, stream_mode=["tasks", "updates"]
        ):
            if mode == "tasks":
                await _on_task(run, chunk)
            elif mode == "updates":
                await _on_update(run, chunk)
        if run.state == "waiting_for_pm":
            return
        if run.error is not None:
            raise ResolveError(run.error)
        if run.analysis is None:
            raise RuntimeError("graph finished without an analysis")
        run.state = "done"
        await run.emit(_completion_event(run.analysis))
    except Exception as exc:  # noqa: BLE001
        if not isinstance(exc, ResolveError):
            log.exception("analysis %s failed", run.run_id)
        run.state = "failed"
        run.error = str(exc) if isinstance(exc, ResolveError) else f"{type(exc).__name__}: {exc}"
        await run.emit({"event": "run_failed", "error": run.error})


async def _on_task(run: _Run, task: dict[str, Any]) -> None:
    node = task.get("name", "")
    agent = _NODE_TO_AGENT.get(node)
    if "result" not in task and "error" not in task:  # task start
        if agent:
            run.agents[agent] = "running"
        await run.emit({"event": "node_start", "node": node, "agent": agent})
    elif task.get("error"):
        if agent:
            run.agents[agent] = "failed"
        await run.emit(
            {"event": "node_error", "node": node, "agent": agent, "error": str(task["error"])}
        )


async def _on_update(run: _Run, update: dict[str, Any]) -> None:
    for node, values in update.items():
        if node == "__interrupt__":
            run.gate = values[0].value if values else None
            run.state = "waiting_for_pm"
            await run.emit({"event": "gate_waiting", "gate": run.gate})
            continue
        values = values or {}
        agent = _NODE_TO_AGENT.get(node)
        event: dict[str, Any] = {"event": "node_finish", "node": node, "agent": agent}
        if agent and agent in (values.get("reports") or {}):
            report = values["reports"][agent]
            run.agents[agent] = report.status
            event.update(
                status=report.status, n_findings=len(report.findings), summary=report.summary
            )
        if values.get("brief") is not None:
            run.brief = values["brief"]
            event["brief"] = run.brief.model_dump(mode="json")
        if values.get("resolve_error"):
            run.error = values["resolve_error"]
            event["error"] = run.error
        if values.get("analysis") is not None:
            run.analysis = values["analysis"]
        await run.emit(event)


async def get_analysis(run_id: str) -> RunStatus:
    run = _runs.get(run_id)
    if run is not None:
        return run.status()
    analysis = _load_persisted(run_id)  # survives restarts
    if analysis is None:
        raise KeyError(f"unknown run_id {run_id}")
    return RunStatus(
        run_id=run_id,
        state="done",
        agents={a: r.status for a, r in analysis.reports.items()},
        analysis=analysis,
        brief=analysis.brief,
        ontology_persistence=analysis.ontology_persistence,
    )


def _completion_event(analysis: SituationAnalysis) -> dict[str, Any]:
    outcome = analysis.ontology_persistence
    return {
        "event": "run_finished",
        "ontology_persistence": outcome.model_dump(mode="json") if outcome is not None else None,
    }


async def stream_analysis(run_id: str) -> AsyncIterator[dict[str, Any]]:
    """Node start/finish events for live progress; replays past events, ends when the run ends."""
    run = _runs.get(run_id)
    if run is None:
        analysis = _load_persisted(run_id)
        if analysis is None:
            raise KeyError(f"unknown run_id {run_id}")
        yield {"run_id": run_id, **_completion_event(analysis)}
        return
    sent = 0
    while True:
        while sent < len(run.events):
            yield run.events[sent]
            sent += 1
        if run.state != "running":
            return
        async with run.changed:
            if sent >= len(run.events) and run.state == "running":
                await run.changed.wait()


def _load_persisted(run_id: str) -> SituationAnalysis | None:
    path = get_settings().analyses_dir / f"{run_id}.json"
    if not path.exists():
        return None
    return SituationAnalysis.model_validate_json(path.read_text())


async def _load_analysis(run_id: str) -> SituationAnalysis:
    run = _runs.get(run_id)
    if run is not None and run.analysis is not None:
        return run.analysis
    analysis = _load_persisted(run_id)
    if analysis is None:
        raise KeyError(f"no finished analysis for run_id {run_id}")
    return analysis


# ---------------------------------------------------------------- explain


async def explain(run_id: str, question: str, finding_id: str | None = None) -> Explanation:
    """Answer only from the stored evidence of a run, citing finding/source ids in every sentence."""
    analysis = await _load_analysis(run_id)
    findings = [f for r in analysis.reports.values() for f in r.findings]
    sources: dict[str, Source] = {s.id: s for r in analysis.reports.values() for s in r.sources}
    if finding_id is not None:
        targets = [f for f in findings if f.id == finding_id]
        if not targets:
            raise KeyError(f"unknown finding_id {finding_id} in run {run_id}")
    else:
        targets = await retrieve(question, findings, EXPLAIN_TOP_K)
    return await answer_from_evidence(analysis.brief, targets, sources, question)
