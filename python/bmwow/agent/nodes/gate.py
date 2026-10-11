"""gate_requirements: the PM reviews requirement candidates, one action per step.

The node pauses with `interrupt()` and shows the candidates; the PM's answer is one action:

- {"action": "approve" | "reject", "candidate_id": "REQ-1", "reason": "..."}
- {"action": "constrain", "candidate_id": "REQ-1", "kind": "freeze|cap|floor|set|deprioritize",
   "value": 520, "reason": "..."}                       → target / intent / priority recomputed by code
- {"action": "constrain_text", "text": "keep range as it is, max 520 km for charging"}
                                                        → an LLM proposes structured constraints,
                                                          shown as pending until the PM confirms
- {"action": "confirm"} / {"action": "cancel"}          → apply or drop the pending constraints
- {"action": "why", "candidate_id": "REQ-1", "question": "..."}
                                                        → answer only from the candidate's evidence
- {"action": "done"}                                    → continue the pipeline

Exactly one interrupt per node execution, so resuming never repeats an LLM call; the graph loops back
to this node until "done". Decisions stay in the run state and the saved analysis.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from langgraph.types import interrupt
from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import Constraint, GateEvent, RequirementCandidate, Source

from ..candidates import add_constraint
from ..config import get_settings
from ..explain import answer_from_evidence
from ..llm import get_chat_model
from ..prompting import render_prompt
from ..taxonomy import load_taxonomy
from ..validation import numbers_in
from .candidate import word
from .common import structured_call

log = logging.getLogger(__name__)

ACTIONS = ("approve", "reject", "constrain", "constrain_text", "confirm", "cancel", "why", "done")
_NEEDS_VALUE = {"cap", "floor", "set"}


class ParsedConstraint(BaseModel):
    candidate_id: str
    kind: Literal["freeze", "cap", "floor", "set", "deprioritize"]
    value: float | None = Field(description="only for cap / floor / set; a number the PM wrote")
    reason: str


class ParsedConstraints(BaseModel):
    constraints: list[ParsedConstraint]


def render_candidates(candidates: list[RequirementCandidate]) -> str:
    lines = []
    for c in candidates:
        target = (
            f"{c.target.operator} {c.target.value:g} {c.target.unit} {c.target.condition}".strip()
            if c.target
            else "to be set"
        )
        options = ", ".join(f"{o.label} {o.value:g} {o.unit}" for o in c.options) or "none"
        lines.append(
            f"- {c.id} [{c.status}, priority {c.priority}] {c.title}: intent {c.change_intent}, "
            f"target {target}; options: {options}"
        )
    return "\n".join(lines) or "- none"


def gate_payload(state: dict[str, Any]) -> dict[str, Any]:
    candidates = state.get("requirement_candidates") or []
    log_ = state.get("gate_log") or []
    return {
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "pending_constraints": state.get("pending_constraints") or [],
        "last": log_[-1].model_dump(mode="json") if log_ else None,
        "actions": list(ACTIONS),
    }


async def gate_requirements(state: dict[str, Any]) -> dict[str, Any]:
    action = interrupt(gate_payload(state))
    if not isinstance(action, dict):
        action = {"action": str(action)}
    candidates: list[RequirementCandidate] = list(state.get("requirement_candidates") or [])
    pending: list[dict[str, Any]] = list(state.get("pending_constraints") or [])
    log_: list[GateEvent] = list(state.get("gate_log") or [])
    name = str(action.get("action", ""))
    cid = action.get("candidate_id")
    event = GateEvent(action=name, candidate_id=cid, detail=str(action.get("reason") or ""))
    done = False
    try:
        if name == "done":
            done = True
            event.response = "review finished"
        elif name in ("approve", "reject"):
            i = _index(candidates, cid)
            candidates[i] = candidates[i].model_copy(
                update={
                    "status": "approved" if name == "approve" else "rejected",
                    "decision_reason": str(action.get("reason") or ""),
                }
            )
            event.response = f"{cid} {candidates[i].status}"
        elif name == "constrain":
            constraint = _constraint(action)
            i = _index(candidates, cid)
            candidates[i] = await _apply(state, candidates[i], constraint)
            event.response = _describe(candidates[i])
        elif name == "constrain_text":
            pending = await _parse(state, candidates, str(action.get("text") or ""))
            event.detail = str(action.get("text") or "")
            event.response = (
                "Proposed (confirm or cancel): "
                + "; ".join(
                    f"{p['candidate_id']}: {p['kind']} {p.get('value') or ''}" for p in pending
                )
                if pending
                else "No constraint recognized; use a structured constraint instead."
            )
        elif name == "confirm":
            for p in pending:
                i = _index(candidates, p["candidate_id"])
                candidates[i] = await _apply(
                    state,
                    candidates[i],
                    Constraint(**{k: v for k, v in p.items() if k != "candidate_id"}),
                )
            event.response = f"applied {len(pending)} constraint(s)"
            pending = []
        elif name == "cancel":
            event.response = f"dropped {len(pending)} pending constraint(s)"
            pending = []
        elif name == "why":
            i = _index(candidates, cid)
            answer = await _why(state, candidates[i], str(action.get("question") or "Why?"))
            event.detail = str(action.get("question") or "")
            event.response, event.cited_ids = answer.answer, answer.cited_ids
        else:
            event.response = f"unknown action {name!r}; use one of {', '.join(ACTIONS)}"
    except (KeyError, ValueError) as exc:
        event.response = f"rejected: {exc}"
    return {
        "requirement_candidates": candidates,
        "pending_constraints": pending,
        "gate_log": [*log_, event],
        "gate_done": done,
    }


def after_gate(state: dict[str, Any]) -> str:
    return "collect" if state.get("gate_done") else "gate_requirements"


def _index(candidates: list[RequirementCandidate], cid: Any) -> int:
    for i, c in enumerate(candidates):
        if c.id == cid:
            return i
    raise KeyError(f"unknown candidate {cid!r}")


def _constraint(action: dict[str, Any]) -> Constraint:
    kind = action.get("kind")
    value = action.get("value")
    if kind in _NEEDS_VALUE and value is None:
        raise ValueError(f"{kind} needs a value")
    return Constraint(
        kind=kind,
        value=float(value) if value is not None else None,
        reason=str(action.get("reason") or ""),
    )


async def _apply(
    state: dict[str, Any], c: RequirementCandidate, constraint: Constraint
) -> RequirementCandidate:
    updated = add_constraint(c, constraint)
    pkg = next(
        (p for p in state.get("evidence_packages") or [] if p.attribute == c.attribute), None
    )
    return await word(state["brief"], await load_taxonomy(), updated, pkg)


def _describe(c: RequirementCandidate) -> str:
    target = f"{c.target.operator} {c.target.value:g} {c.target.unit}" if c.target else "to be set"
    return (
        f"{c.id}: intent {c.change_intent}, target {target}, priority {c.priority}. {c.statement}"
    )


async def _parse(
    state: dict[str, Any], candidates: list[RequirementCandidate], text: str
) -> list[dict[str, Any]]:
    """PM free text → structured constraints, validated by code; never applied without confirm."""
    if not text.strip():
        raise ValueError("empty instruction")
    if not get_settings().allow_llm_on_internal_data:
        raise ValueError(
            "free-text constraints need an LLM (ALLOW_LLM_ON_INTERNAL_DATA=true); "
            "use a structured constraint"
        )
    prompt = render_prompt(
        "gate_constraint",
        brief=state["brief"],
        taxonomy=await load_taxonomy(),
        candidates=render_candidates(candidates),
        text=text,
    )
    out = await structured_call(get_chat_model("cheap"), ParsedConstraints, prompt)
    ids = {c.id for c in candidates}
    written = numbers_in(text)
    parsed = []
    for p in out.constraints:
        if p.candidate_id not in ids:
            continue
        if p.kind in _NEEDS_VALUE and (p.value is None or p.value not in written):
            continue  # a value the PM did not write is never applied
        value = p.value if p.kind in _NEEDS_VALUE else None
        parsed.append(
            {
                "candidate_id": p.candidate_id,
                "kind": p.kind,
                "value": value,
                "reason": re.sub(r"\s+", " ", p.reason).strip(),
                "source_text": text,
            }
        )
    return parsed


async def _why(state: dict[str, Any], c: RequirementCandidate, question: str):
    reports = state.get("reports") or {}
    findings = [f for r in reports.values() for f in r.findings if f.id in set(c.evidence_ids)]
    sources: dict[str, Source] = {s.id: s for r in reports.values() for s in r.sources}
    q = f"{question} (about requirement candidate {c.id}: {c.statement})"
    return await answer_from_evidence(state["brief"], findings, sources, q)
