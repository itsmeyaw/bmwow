import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from bmwow.agent import service
from bmwow.agent.candidates import add_constraint, wording_guard
from bmwow.agent.config import get_settings
from bmwow.agent.models.evidence import (
    AcceptanceCriterion,
    Constraint,
    RequirementCandidate,
    Target,
    TargetOption,
)
from bmwow.agent.supervisor import build_graph, checkpoint_serde
from bmwow.agent.validation import numbers_in


async def run(analysis_request):
    return (await build_graph().ainvoke({"run_id": "cand", "request": analysis_request}))[
        "analysis"
    ]


def by_attr(analysis, attribute):
    return next(c for c in analysis.requirement_candidates if c.attribute == attribute)


async def test_candidates_are_quantitative_and_built_by_code(analysis_request):
    analysis = await run(analysis_request)
    cands = analysis.requirement_candidates
    assert [c.id for c in cands] == [f"REQ-{i}" for i in range(1, len(cands) + 1)]
    # flagged or unclear judgments never become candidates
    assessed = {a.attribute: a for a in analysis.feature_assessments}
    for c in cands:
        assert assessed[c.attribute].guard_status != "flagged"
        assert c.assessment in {"gap", "demand", "hygiene_factor", "strength"}
        assert numbers_in(c.statement), c.statement  # quantitative
        assert c.status == "proposed" and c.evidence_ids
    rng = by_attr(analysis, "real_world_range")
    assert rng.change_intent == "improve" and rng.baseline_status == "known_present"
    assert rng.target.value == 500 and rng.target.operator == ">=" and rng.target.unit == "km"
    assert rng.target.basis == "proposed_target" and "median" in rng.target.rule
    assert {o.label: o.value for o in rng.options} == {
        "ours": 455,
        "competitor_median": 500,
        "best_in_class": 575,
    }
    assert rng.criterion.operator == ">=" and rng.criterion.verification_method == "benchmark_test"
    # lower is better for charging time: the target is an upper bound
    charging = by_attr(analysis, "fast_charging")
    assert charging.lower_is_better and charging.target.operator == "<="
    assert charging.target.value <= next(o.value for o in charging.options if o.label == "ours")
    # the catalog says "not available": introduce, not improve
    vent = by_attr(analysis, "seat_ventilation")
    assert vent.baseline_status == "known_absent" and vent.change_intent == "introduce"
    assert vent.target is None and "to be set by the PM" in vent.criterion.description
    # the LLM wording passed the guard after one revision and states the target
    assert rng.wording == "llm" and all(g.ok for g in rng.guard) and "500" in rng.statement


async def test_template_wording_without_llm_clearance(analysis_request, monkeypatch):
    monkeypatch.setenv("ALLOW_LLM_ON_INTERNAL_DATA", "false")
    get_settings.cache_clear()
    analysis = await run(analysis_request)
    # no judgment without the LLM, so no candidates; the skeleton logic is tested below
    assert analysis.requirement_candidates == []


def _candidate(lower: bool = False) -> RequirementCandidate:
    unit, ours, median, best = ("min", 32, 28, 22) if lower else ("km", 455, 500, 575)
    target = Target(
        operator="<=" if lower else ">=",
        value=median,
        unit=unit,
        condition="wltp",
        basis="proposed_target",
        rule="competitor median (gap)",
    )
    return RequirementCandidate(
        id="REQ-1",
        attribute="real_world_range",
        title="real world range",
        assessment="gap",
        change_intent="improve",
        baseline_status="known_present",
        baseline_rationale="present",
        statement="",
        customer_value="",
        proposed_target=target,
        target=target,
        lower_is_better=lower,
        options=[
            TargetOption(label="ours", value=ours, unit=unit, condition="wltp"),
            TargetOption(label="competitor_median", value=median, unit=unit, condition="wltp"),
            TargetOption(label="best_in_class", value=best, unit=unit, condition="wltp"),
        ],
        customer_facts=["21.3% of feedback items in EU report a problem (13 of 61)"],
        criterion=AcceptanceCriterion(
            description="x", basis="proposed_target", verification_method="analysis"
        ),
    )


@pytest.mark.parametrize("lower", [False, True])
def test_constraints_recompute_target_intent_and_priority(lower):
    c = _candidate(lower)
    capped = add_constraint(c, Constraint(kind="cap", value=480 if not lower else 30))
    assert capped.target.value == (480 if not lower else 30)  # less ambitious than the median
    assert capped.target.basis == "human_set_target" and "480" in capped.statement or lower
    loose_cap = add_constraint(c, Constraint(kind="cap", value=600 if not lower else 20))
    assert loose_cap.target.value == (500 if not lower else 28)  # cap above the proposal: no change
    floor = add_constraint(c, Constraint(kind="floor", value=520 if not lower else 25))
    assert floor.target.value == (520 if not lower else 25)
    frozen = add_constraint(c, Constraint(kind="freeze", reason="platform carry-over"))
    assert frozen.change_intent == "retain" and frozen.target.operator == "="
    assert frozen.target.value == (455 if not lower else 32) and "platform" in frozen.target.rule
    low = add_constraint(c, Constraint(kind="deprioritize", reason="not important"))
    assert low.priority == "low" and low.target == c.target
    exact = add_constraint(frozen, Constraint(kind="set", value=510))
    assert exact.target.value == 510 and exact.target.operator == "="  # later constraints win
    assert numbers_in(exact.statement) and exact.criterion.target == 510


def test_wording_guard():
    c = add_constraint(_candidate(), Constraint(kind="floor", value=520))
    ok = wording_guard(c, "Reach >= 520 km WLTP; 21.3% of EU owners complain.", "x", "")
    assert all(g.ok for g in ok)
    bad = {g.rule for g in wording_guard(c, "Reach 600 km.", "x", "") if not g.ok}
    assert {"numbers_from_facts", "states_the_target"} <= bad
    assert "quantitative" in {g.rule for g in wording_guard(c, "Reach more.", "x", "") if not g.ok}


async def test_pm_gate_actions(analysis_request):
    graph = build_graph(checkpointer=InMemorySaver(serde=checkpoint_serde()), pm_gate=True)
    config = {"configurable": {"thread_id": "gate"}}
    out = await graph.ainvoke({"run_id": "gate", "request": analysis_request}, config)
    payload = out["__interrupt__"][0].value
    ids = {c["attribute"]: c["id"] for c in payload["candidates"]}
    rng, charging = ids["real_world_range"], ids["fast_charging"]

    async def act(action):
        result = await graph.ainvoke(Command(resume=action), config)
        return result["__interrupt__"][0].value if "__interrupt__" in result else result

    p = await act(
        {
            "action": "constrain",
            "candidate_id": rng,
            "kind": "cap",
            "value": 480,
            "reason": "battery cost",
        }
    )
    c = next(x for x in p["candidates"] if x["id"] == rng)
    assert c["target"]["value"] == 480 and c["target"]["basis"] == "human_set_target"
    assert "480" in c["statement"]
    p = await act(
        {"action": "constrain_text", "text": f"{charging} not important; {rng} max 470 km"}
    )
    pending = {(x["candidate_id"], x["kind"], x["value"]) for x in p["pending_constraints"]}
    # the planted value the PM never wrote and the unknown candidate are dropped
    assert pending == {(charging, "deprioritize", None), (rng, "cap", 470.0)}
    p = await act({"action": "confirm"})
    assert not p["pending_constraints"]
    assert next(x for x in p["candidates"] if x["id"] == charging)["priority"] == "low"
    p = await act({"action": "why", "candidate_id": rng, "question": "Why improve range?"})
    assert p["last"]["cited_ids"] and set(p["last"]["cited_ids"]) <= set(
        next(x for x in p["candidates"] if x["id"] == rng)["evidence_ids"]
    ) | {s for s in p["last"]["cited_ids"] if s.startswith("fb:")}
    p = await act({"action": "approve", "candidate_id": rng, "reason": "agreed with 470"})
    p = await act({"action": "teleport"})
    assert "unknown action" in p["last"]["response"]
    p = await act({"action": "approve", "candidate_id": "REQ-999"})
    assert "rejected" in p["last"]["response"]
    final = await act({"action": "done"})
    analysis = final["analysis"]
    approved = next(c for c in analysis.requirement_candidates if c.id == rng)
    assert approved.status == "approved" and approved.target.value == 470
    assert [k.kind for k in approved.constraints] == ["cap", "cap"]
    assert [e.action for e in analysis.gate_log][-1] == "done"


async def test_service_pauses_for_the_pm_and_resumes(analysis_request):
    run_id = await service.start_analysis(analysis_request, pm_gate=True)
    for _ in range(200):
        status = await service.get_analysis(run_id)
        if status.state != "running":
            break
        await asyncio.sleep(0.05)
    assert status.state == "waiting_for_pm" and status.gate["candidates"]
    first = status.gate["candidates"][0]["id"]
    status = await service.gate_action(run_id, {"action": "reject", "candidate_id": first})
    assert status.state == "waiting_for_pm" and "rejected" in status.gate["last"]["response"]
    status = await service.gate_action(run_id, {"action": "done"})
    assert status.state == "done" and status.gate is None
    rejected = next(c for c in status.analysis.requirement_candidates if c.id == first)
    assert rejected.status == "rejected"
    with pytest.raises(ValueError):
        await service.gate_action(run_id, {"action": "done"})
    await service.aclose()


def test_problem_reports_mean_the_feature_exists_today():
    from bmwow.agent.candidates import _baseline
    from bmwow.agent.models.evidence import EvidencePackage, SubTheme

    def theme(direction, k):
        return SubTheme(
            attribute="x",
            direction=direction,
            name="auto start-stop",
            k=k,
            of=50,
            method="aspect_term",
            source_ids=[],
        )

    pkg = EvidencePackage(
        attribute="x", label="x", importance=0.1, sub_themes=[theme("problem", 9)]
    )
    status, why = _baseline(pkg, None, theme("problem", 9))
    assert status == "known_present" and "9 feedback items" in why
    wish_only = EvidencePackage(
        attribute="x", label="x", importance=0.1, sub_themes=[theme("request", 9)]
    )
    assert _baseline(wish_only, None, theme("request", 9))[0] == "unknown"


def test_one_unavailable_option_does_not_make_the_feature_absent():
    from bmwow.agent.candidates import _baseline
    from bmwow.agent.models.evidence import EvidencePackage, FactRef

    def fact(i, text):
        return FactRef(finding_id=f"F-{i}", agent="baseline", subject="G60", text=text)

    mixed = EvidencePackage(
        attribute="x",
        label="x",
        importance=0.1,
        ours=[fact(1, "Highway assistant, standard."), fact(2, "Option Y, unavailable.")],
    )
    assert _baseline(mixed, None)[0] == "known_present"
    none = mixed.model_copy(update={"ours": [fact(2, "Option Y, unavailable.")]})
    assert _baseline(none, None)[0] == "known_absent"
