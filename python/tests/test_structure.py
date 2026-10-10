import pytest

from bmwow.agent.config import get_settings
from bmwow.agent.models.evidence import (
    CustomerSignal,
    EvidencePackage,
    SituationAnalysis,
    TrendSignal,
    ValueComparison,
)
from bmwow.agent.rules import load_rules
from bmwow.agent.structure import guard, render_package
from bmwow.agent.supervisor import build_graph


async def run(analysis_request):
    out = await build_graph().ainvoke({"run_id": "structure", "request": analysis_request})
    return out["analysis"]


def package(analysis, attribute):
    return next(p for p in analysis.evidence_packages if p.attribute == attribute)


async def test_packages_hold_facts_from_all_views(analysis_request):
    analysis = await run(analysis_request)
    pkg = package(analysis, "real_world_range")
    assert pkg.ours and pkg.customers and pkg.finding_ids
    # WLTP and NEDC values never mix; ours (WLTP) is compared with WLTP competitors only
    wltp = next(v for v in pkg.competitor_values if v.condition == "wltp")
    nedc = next(v for v in pkg.competitor_values if v.condition == "nedc")
    assert wltp.ours == 455 and nedc.ours is None
    assert 1 < wltp.ours_rank <= wltp.field_size == wltp.n + 1 and wltp.ours_vs_median < 0
    assert any("rank" in c and "WLTP" not in c or "wltp" in c for c in pkg.comparisons)
    assert pkg.importance == max(s.ci_low for s in pkg.customers if s.direction == "problem")
    # packages are ranked by importance; coverage names missing views
    importances = [p.importance for p in analysis.evidence_packages]
    assert importances == sorted(importances, reverse=True)
    assert any("missing: " in c for p in analysis.evidence_packages for c in p.coverage)
    # every id in a package resolves to a finding or source of the reports
    ids = {f.id for r in analysis.reports.values() for f in r.findings}
    ids |= {s.id for r in analysis.reports.values() for s in r.sources}
    for p in analysis.evidence_packages:
        assert set(p.finding_ids) <= ids and {q.source_id for q in p.quotes} <= ids


async def test_judgments_are_guarded_revised_or_flagged(analysis_request):
    analysis = await run(analysis_request)
    judged = {
        a.attribute: a for a in analysis.feature_assessments if a.assessment != "not_assessed"
    }
    assert judged
    revised = judged["real_world_range"]
    assert revised.guard_status == "revised" and all(c.ok for c in revised.guard)
    assert revised.assessment == "gap" and "99" not in revised.reasoning
    assert revised.cited_ids and all(i.startswith("F-") for i in revised.cited_ids)
    flagged = judged["reliable_software"]
    assert flagged.guard_status == "flagged"
    failed = {c.rule for c in flagged.guard if not c.ok}
    assert {"cited_ids_exist", "numbers_from_package"} <= failed
    # one assessment per package, ranking kept; the tail beyond the budget stays not_assessed
    assert [a.attribute for a in analysis.feature_assessments] == [
        p.attribute for p in analysis.evidence_packages
    ]
    limit = load_rules().structure.max_judged_features
    assert all(a.assessment == "not_assessed" for a in analysis.feature_assessments[limit:])


async def test_judgment_stays_off_without_clearance(analysis_request, monkeypatch, fake_env):
    monkeypatch.setenv("ALLOW_LLM_ON_INTERNAL_DATA", "false")
    get_settings.cache_clear()
    analysis = await run(analysis_request)
    assert analysis.evidence_packages
    assert all(a.assessment == "not_assessed" for a in analysis.feature_assessments)
    assert "ALLOW_LLM_ON_INTERNAL_DATA" in analysis.feature_assessments[0].note
    assert not any("# Rubric" in p for p in fake_env["analyst"].prompts)


async def test_hand_off_round_trips(analysis_request):
    analysis = await run(analysis_request)
    again = SituationAnalysis.model_validate_json(analysis.model_dump_json())
    assert again.evidence_packages == analysis.evidence_packages
    assert again.feature_assessments == analysis.feature_assessments


def _pkg(**kw) -> EvidencePackage:
    base = dict(
        attribute="real_world_range",
        label="real world range",
        importance=0.05,
        customers=[
            CustomerSignal(
                finding_id="F-feedback-1",
                direction="problem",
                region="EU",
                share=0.12,
                k=12,
                n=100,
                ci_low=0.07,
                ci_high=0.2,
                thin=False,
            ),
            CustomerSignal(
                finding_id="F-feedback-2",
                direction="strength",
                region="EU",
                share=0.04,
                k=4,
                n=100,
                ci_low=0.016,
                ci_high=0.1,
                thin=True,
            ),
        ],
        competitor_values=[
            ValueComparison(
                unit="km",
                condition="wltp",
                region=None,
                n=3,
                minimum=480,
                median=520,
                maximum=575,
                lower_is_better=False,
                ours=455,
                ours_rank=4,
                field_size=4,
                ours_vs_median=-0.125,
                finding_ids=["F-competition-1"],
            )
        ],
        trends=[
            TrendSignal(
                finding_id="F-trends-1",
                claim="Charging networks grow.",
                polarity="demand",
                horizon="1-2y",
                n_independent_sources=1,
                thin=True,
            )
        ],
        finding_ids=["F-feedback-1", "F-feedback-2", "F-competition-1", "F-trends-1"],
        source_ids=["fb:1"],
    )
    base.update(kw)
    return EvidencePackage(**base)


def failed(checks):
    return {c.rule for c in checks if not c.ok}


def test_guard_rules():
    rules = load_rules()
    pkg = _pkg()
    assert "12.0%" in render_package(pkg) or "12" in render_package(pkg)
    ok = guard(
        pkg, "gap", "limited", "EU complaints and a median of 520 km.", ["F-feedback-1"], rules
    )
    assert failed(ok) == set()
    assert "cited_ids_exist" in failed(guard(pkg, "gap", "limited", "x", ["F-x-9"], rules))
    assert "cites_evidence" in failed(guard(pkg, "gap", "limited", "x", [], rules))
    assert "numbers_from_package" in failed(
        guard(pkg, "gap", "limited", "37% complain", ["F-feedback-1"], rules)
    )
    # widespread needs CI lower bound >= 2%: the problem share qualifies, a thin praise alone does not
    assert not failed(guard(pkg, "gap", "widespread", "x", ["F-feedback-1"], rules))
    low = _pkg(customers=[pkg.customers[1]])
    assert "widespread_supported" in failed(
        guard(low, "strength", "widespread", "thin", ["F-feedback-2"], rules)
    )
    # each assessment needs its kind of evidence
    assert "strength_supported" in failed(
        guard(pkg, "strength", "limited", "x", ["F-feedback-1"], rules)
    )
    assert "demand_supported" not in failed(
        guard(pkg, "demand", "limited", "thin trend", ["F-trends-1"], rules)
    )
    assert "hygiene_factor_supported" in failed(
        guard(pkg, "hygiene_factor", "limited", "x", ["F-competition-1"], rules)
    )
    # citing thin evidence requires saying so
    assert "thin_evidence_acknowledged" in failed(
        guard(pkg, "demand", "limited", "Strong trend.", ["F-trends-1"], rules)
    )


@pytest.mark.parametrize("assessment", ["unclear"])
def test_unclear_needs_no_citation(assessment):
    assert not failed(guard(_pkg(), assessment, "unclear", "Evidence too thin.", [], load_rules()))


async def test_gap_fill_researches_important_features_once(analysis_request, monkeypatch, fake_env):
    # Only range is a core feature, so software complaints have no competitor evidence at first.
    rules = load_rules()
    monkeypatch.setattr(rules.competition, "core_features", {"real_world_range": "range WLTP km"})
    analysis = await run(analysis_request)
    competition = analysis.reports["competition"]
    gap = next(a for a in competition.availability if a.source == "gap_fill")
    assert "reliable_software" in gap.reason
    pkg = package(analysis, "reliable_software")
    assert pkg.competitor_values or pkg.competitor_facts
    ids = [f.id for f in competition.findings]
    assert len(ids) == len(set(ids))  # merged findings continue the id sequence
    queries = [q for q, _ in fake_env["provider"].searches if "reliable software" in q]
    assert queries  # the targeted round searched the gap feature (by name: not a core feature)
    # one round only, then the judgment runs on the completed packages
    assert analysis.feature_assessments and any(
        a.assessment != "not_assessed" for a in analysis.feature_assessments
    )


async def test_no_gap_fill_below_the_importance_threshold(analysis_request, monkeypatch):
    monkeypatch.setattr(load_rules().gap_fill, "min_customer_ci_low", 1.0)
    analysis = await run(analysis_request)
    assert not any(a.source == "gap_fill" for a in analysis.reports["competition"].availability)


async def test_failed_gap_fill_is_reported_unavailable(analysis_request, monkeypatch):
    from bmwow.agent.nodes import competition as competition_node

    rules = load_rules()
    monkeypatch.setattr(rules.competition, "core_features", {"real_world_range": "range WLTP km"})

    async def broken(ctx, competitors, features):
        raise TimeoutError("search backend timed out")

    monkeypatch.setattr(competition_node, "research_features", broken)
    analysis = await run(analysis_request)
    competition = analysis.reports["competition"]
    gap = next(a for a in competition.availability if a.source == "gap_fill")
    assert gap.status == "unavailable" and "TimeoutError" in gap.reason
    assert any("gap_fill" in e for e in competition.errors)
