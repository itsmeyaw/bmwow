"""Public entry points for `src/api/` (AGENT_SPEC §7)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

import numpy as np
from pydantic import BaseModel, Field

from src.models.evidence import (AGENT_NAMES, AgentName, AnalysisRequest, Finding, ProductBrief, SituationAnalysis,
                                 Source, SupportedModel)

from .config import get_settings
from .llm import get_chat_model, get_embeddings
from .prompting import render_prompt
from .registry import ResolveError, load_registry
from .resolve import check_brief, resolve_request
from .sources import utcnow
from .supervisor import AGENT_NODE_NAMES, build_graph
from .taxonomy import load_taxonomy
from .validation import sentence_supported

log = logging.getLogger(__name__)

AgentRunState = Literal["pending", "running", "ok", "partial", "failed"]
EXPLAIN_TOP_K = 8
_NODE_TO_AGENT = {node: agent for agent, node in AGENT_NODE_NAMES.items()}


class RunStatus(BaseModel):
    run_id: str
    state: Literal["running", "done", "failed"]
    agents: dict[AgentName, AgentRunState]
    analysis: SituationAnalysis | None = None
    error: str | None = None  # optional addition: why the run failed (e.g. the request did not resolve)
    brief: ProductBrief | None = None  # optional addition: the resolved brief, as soon as it exists


class Explanation(BaseModel):
    answer: str
    cited_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- run registry


@dataclass
class _Run:
    run_id: str
    state: Literal["running", "done", "failed"] = "running"
    agents: dict[AgentName, AgentRunState] = field(default_factory=lambda: {a: "pending" for a in AGENT_NAMES})
    analysis: SituationAnalysis | None = None
    error: str | None = None
    brief: ProductBrief | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append({"run_id": self.run_id, "ts": utcnow().isoformat(), **event})
        async with self.changed:
            self.changed.notify_all()

    def status(self) -> RunStatus:
        return RunStatus(run_id=self.run_id, state=self.state, agents=dict(self.agents),
                         analysis=self.analysis, error=self.error, brief=self.brief)


_runs: dict[str, _Run] = {}
_graph_cache: dict[int, tuple[Any, Any]] = {}  # id(loop) -> (graph, sqlite connection)


async def _get_graph() -> Any:
    """Compiled graph with the SQLite checkpointer, one per event loop (aiosqlite is loop-bound)."""
    loop = asyncio.get_running_loop()
    cached = _graph_cache.get(id(loop))
    if cached is not None:
        return cached[0]
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = get_settings().checkpoint_db
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(path))
    graph = build_graph(checkpointer=AsyncSqliteSaver(conn))
    _graph_cache[id(loop)] = (graph, conn)
    return graph


async def aclose() -> None:
    """Cancel running analyses and close the checkpointer connection (call on API shutdown)."""
    for run in _runs.values():
        if run.task is not None and not run.task.done():
            run.task.cancel()
    cached = _graph_cache.pop(id(asyncio.get_running_loop()), None)
    if cached is not None:
        await cached[1].close()


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


async def start_analysis(request: AnalysisRequest, brief_override: ProductBrief | None = None) -> str:
    """Create a run id, launch the graph in the background and return immediately.

    `brief_override` = the PM-corrected brief from `resolve()`, used instead of re-resolving. Registry
    checks run before launching, so invalid input raises `ResolveError` here instead of a failed run.
    """
    registry = await load_registry()
    registry.check(request)
    if brief_override is not None:
        await check_brief(request, brief_override, registry)
    run_id = uuid.uuid4().hex[:12]
    run = _Run(run_id=run_id, brief=brief_override)
    _runs[run_id] = run
    run.task = asyncio.create_task(_execute(run, request, brief_override), name=f"analysis-{run_id}")
    return run_id


async def _execute(run: _Run, request: AnalysisRequest, brief: ProductBrief | None) -> None:
    await run.emit({"event": "run_started"})
    try:
        graph = await _get_graph()
        config = {"configurable": {"thread_id": run.run_id}}
        inputs: dict[str, Any] = {"run_id": run.run_id, "request": request}
        if brief is not None:
            inputs["brief"] = brief
        async for mode, chunk in graph.astream(inputs, config, stream_mode=["tasks", "updates"]):
            if mode == "tasks":
                await _on_task(run, chunk)
            elif mode == "updates":
                await _on_update(run, chunk)
        if run.error is not None:
            raise ResolveError(run.error)
        if run.analysis is None:
            raise RuntimeError("graph finished without an analysis")
        run.state = "done"
        await run.emit({"event": "run_finished"})
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
        await run.emit({"event": "node_error", "node": node, "agent": agent, "error": str(task["error"])})


async def _on_update(run: _Run, update: dict[str, Any]) -> None:
    for node, values in update.items():
        values = values or {}
        agent = _NODE_TO_AGENT.get(node)
        event: dict[str, Any] = {"event": "node_finish", "node": node, "agent": agent}
        if agent and agent in (values.get("reports") or {}):
            report = values["reports"][agent]
            run.agents[agent] = report.status
            event.update(status=report.status, n_findings=len(report.findings), summary=report.summary)
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
    return RunStatus(run_id=run_id, state="done", agents={a: r.status for a, r in analysis.reports.items()},
                     analysis=analysis, brief=analysis.brief)


async def stream_analysis(run_id: str) -> AsyncIterator[dict[str, Any]]:
    """Node start/finish events for live progress; replays past events, ends when the run ends."""
    run = _runs.get(run_id)
    if run is None:
        if _load_persisted(run_id) is None:
            raise KeyError(f"unknown run_id {run_id}")
        yield {"run_id": run_id, "event": "run_finished"}
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


class ExplainSentence(BaseModel):
    text: str
    cited_ids: list[str] = Field(description="finding ids (F-...) and/or source ids from the evidence")


class ExplainOutput(BaseModel):
    supported: bool
    sentences: list[ExplainSentence]
    missing: str = Field(description="what evidence is missing; empty if supported")


def _render_finding(f: Finding) -> str:
    q = ""
    if f.quantity:
        value = f"{f.quantity.value:.1%}" if f.quantity.unit == "share" else f"{f.quantity.value:g} {f.quantity.unit}"
        q = f" | quantity: {value} {f.quantity.qualifier}".rstrip()
    w = f" | weight: {f.weight:.1%}" if f.weight != 1.0 else ""
    return (f"[{f.id}] agent={f.agent} attribute={f.attribute} subject={f.subject} polarity={f.polarity} "
            f"confidence={f.confidence}{q}{w} sources={', '.join(f.source_ids)}\n  claim: {f.claim}")


async def _retrieve(question: str, findings: list[Finding], k: int) -> list[Finding]:
    if len(findings) <= k:
        return findings
    emb = get_embeddings()
    texts = [f"{f.attribute} {f.subject}: {f.claim}" for f in findings]
    vecs = np.asarray(await emb.aembed_documents(texts), dtype=float)
    q = np.asarray(await emb.aembed_query(question), dtype=float)
    vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)
    q /= max(float(np.linalg.norm(q)), 1e-12)
    order = np.argsort(-(vecs @ q), kind="stable")[:k]
    return [findings[int(i)] for i in order]


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
        targets = await _retrieve(question, findings, EXPLAIN_TOP_K)
    if not targets:
        return Explanation(answer="The stored analysis has no findings to answer from.", cited_ids=[])

    cited_sources = [sources[sid] for f in targets for sid in f.source_ids if sid in sources]
    cited_sources = list({s.id: s for s in cited_sources}.values())
    context = "\n".join(_render_finding(f) for f in targets) + "\n\nSources:\n" + "\n".join(
        f"[{s.id}] ({s.kind}) {s.title}\n  excerpt: {s.excerpt}" for s in cited_sources)
    allowed = {f.id for f in targets} | {s.id for s in cited_sources}

    prompt = render_prompt("explain_answer", brief=analysis.brief, taxonomy=await load_taxonomy(),
                           question=question, context=context)
    out = await get_chat_model("strong").with_structured_output(ExplainOutput).ainvoke(prompt)
    if isinstance(out, dict):
        out = ExplainOutput.model_validate(out)

    kept = [s for s in out.sentences if sentence_supported(s.text, s.cited_ids, allowed, context)]
    if not out.supported or not kept:
        missing = out.missing.strip() or "evidence that directly addresses the question"
        return Explanation(answer=f"The stored evidence does not support an answer. Missing: {missing}", cited_ids=[])
    answer = " ".join(f"{s.text.strip()} [{', '.join(s.cited_ids)}]" for s in kept)
    cited = list(dict.fromkeys(cid for s in kept for cid in s.cited_ids))
    return Explanation(answer=answer, cited_ids=cited)
