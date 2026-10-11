"""candidate_agent's deterministic parts: requirement candidates from judged features.

Code decides everything that carries a number or a decision: which features become candidates, the
change intent and baseline status (ontology rules: improve/retain need an evidenced baseline; an unknown
baseline is not an absent one), the target options and the default target from comparable competitor
values, the customer facts, and how PM constraints change the target. An LLM may only word the result;
`wording_guard` checks that wording against these facts. Without an LLM the template wording is used.
"""

from __future__ import annotations

from bmwow.agent.models.evidence import (
    AcceptanceCriterion,
    Constraint,
    CustomerSignal,
    EvidencePackage,
    FeatureAssessment,
    GuardCheck,
    ProductBrief,
    RequirementCandidate,
    SubTheme,
    Target,
    TargetOption,
    ValueComparison,
    assessment_label,
)

from .rules import Rules
from .structure import label_of
from .validation import number_in_text, numbers_in, unsupported_numbers

_VERB = {"improve": "improve", "introduce": "offer", "retain": "keep", "remove": "remove"}
_DIRECTIONS = {
    "gap": ("problem", "request"),
    "demand": ("request", "problem"),
    "hygiene_factor": ("problem",),
    "strength": ("strength",),
}


def _fmt(value: float) -> str:
    return f"{value:g}"


def _comparison(pkg: EvidencePackage) -> ValueComparison | None:
    """The comparison a target can be based on: ours known first, then all regions, then the most
    competitors."""
    if not pkg.competitor_values:
        return None
    return sorted(
        pkg.competitor_values,
        key=lambda v: (v.ours is None, v.region is not None, -v.n, v.condition),
    )[0]


def options_of(c: ValueComparison | None) -> list[TargetOption]:
    if c is None:
        return []
    best = c.minimum if c.lower_is_better else c.maximum
    options = []
    if c.ours is not None:
        options.append(TargetOption(label="ours", value=c.ours, unit=c.unit, condition=c.condition))
    options.append(
        TargetOption(
            label="competitor_median",
            value=c.median,
            unit=c.unit,
            condition=c.condition,
            finding_ids=c.finding_ids,
        )
    )
    options.append(
        TargetOption(
            label="best_in_class",
            value=best,
            unit=c.unit,
            condition=c.condition,
            finding_ids=c.finding_ids,
        )
    )
    return options


def _better(a: float, b: float, lower_is_better: bool) -> float:
    return min(a, b) if lower_is_better else max(a, b)


def default_target(assessment: str, c: ValueComparison | None, rules: Rules) -> Target | None:
    """The proposed target: the rule's option for the assessment, never below today's value."""
    if c is None:
        return None
    choice = rules.candidates.default_target.get(assessment, "competitor_median")
    values = {o.label: o.value for o in options_of(c)}
    if choice not in values:
        return None
    value = values[choice]
    rule = {"competitor_median": "competitor median", "best_in_class": "best in class"}.get(
        choice, "today's value"
    )
    if c.ours is not None and _better(value, c.ours, c.lower_is_better) != value:
        value, rule = c.ours, "today's value (already better than the proposed option)"
    return Target(
        operator="<=" if c.lower_is_better else ">=",
        value=value,
        unit=c.unit,
        condition=c.condition,
        basis="proposed_target",
        rule=f"{rule} ({assessment_label(assessment)})",
    )


def _baseline(
    pkg: EvidencePackage, c: ValueComparison | None, theme: SubTheme | None = None
) -> tuple[str, str]:
    used = [
        t
        for t in pkg.sub_themes
        if theme is not None and t.name == theme.name and t.direction == "problem" and t.k > 0
    ]
    if used:  # owners cannot report problems with something the current model lacks
        return (
            "known_present",
            f"Owners of the current model report problems with {used[0].name} "
            f"({used[0].k} feedback items).",
        )
    absent = ("unavailable", "not available", "not offered")
    if pkg.ours and all(any(word in f.text.lower() for word in absent) for f in pkg.ours):
        return "known_absent", "The catalog states the feature is unavailable on the current model."
    if pkg.ours:
        ours = f" ({_fmt(c.ours)} {c.unit}, {c.condition})" if c and c.ours is not None else ""
        return (
            "known_present",
            f"The current model has the feature{ours} per the baseline evidence.",
        )
    return (
        "unknown",
        "No baseline evidence for the current model; unknown does not mean absent.",
    )


def _intent(assessment: str, baseline: str) -> str:
    if assessment == "strength":
        return "retain"
    return "improve" if baseline == "known_present" else "introduce"


def _customer_facts(pkg: EvidencePackage, assessment: str, limit: int) -> list[CustomerSignal]:
    wanted = _DIRECTIONS.get(assessment, ())
    signals = [s for s in pkg.customers if s.direction in wanted]
    return sorted(signals, key=lambda s: (s.thin, s.region is None, -s.k))[:limit]


def render_fact(s: CustomerSignal) -> str:
    where = s.region or "all requested regions"
    verb = {"problem": "report a problem", "request": "ask for it", "strength": "praise it"}.get(
        s.direction, "mention it"
    )
    thin = ", small sample" if s.thin else ""
    return f"{s.share:.1%} of feedback items in {where} {verb} ({s.k} of {s.n}{thin})"


def _sub_theme(pkg: EvidencePackage, assessment: str) -> SubTheme | None:
    wanted = _DIRECTIONS.get(assessment, ())
    themes = [t for t in pkg.sub_themes if t.direction in wanted]
    return max(themes, key=lambda t: (t.k, t.name)) if themes else None


def _criterion(label: str, target: Target | None, evidence: list[str]) -> AcceptanceCriterion:
    if target is None:
        return AcceptanceCriterion(
            description=f"{label}: target value to be set by the PM",
            metric=label,
            basis="proposed_target",
            verification_method="to_be_defined",
            supporting_evidence_ids=evidence,
        )
    return AcceptanceCriterion(
        description=f"{label} {target.operator} {_fmt(target.value)} {target.unit}"
        + (f" ({target.condition})" if target.condition else ""),
        metric=label,
        operator=target.operator,
        target=target.value,
        unit=target.unit,
        basis=target.basis,
        verification_method="benchmark_test" if target.condition else "analysis",
        test_conditions=[target.condition] if target.condition else [],
        supporting_evidence_ids=evidence,
    )


def template_wording(c: RequirementCandidate) -> tuple[str, str]:
    """(statement, customer_value) without an LLM; always quantitative."""
    label = label_of(c.attribute)
    what = f"{label} ({c.sub_theme})" if c.sub_theme else label
    fact = c.customer_facts[0] if c.customer_facts else ""
    if c.target is not None:
        t = c.target
        today = next((o for o in c.options if o.label == "ours"), None)
        now = f"; today {_fmt(today.value)} {today.unit}" if today else ""
        cond = f" {t.condition.upper()}" if t.condition else ""
        statement = (
            f"The successor should {_VERB[c.change_intent]} {what} to {t.operator} "
            f"{_fmt(t.value)} {t.unit}{cond} ({t.rule}{now})"
            + (f", because {fact}." if fact else ".")
        )
    else:
        statement = (
            f"The successor should {_VERB[c.change_intent]} {what}"
            + (f": {fact}" if fact else "")
            + "; target value to be set by the PM."
        )
    value = (
        f"Customers: {fact}." if fact else f"Addresses the {assessment_label(c.assessment)} found."
    )
    return statement, value


def build_candidates(
    packages: list[EvidencePackage],
    assessments: list[FeatureAssessment],
    brief: ProductBrief,
    rules: Rules,
) -> list[RequirementCandidate]:
    """One candidate per judged feature whose assessment qualifies and whose guard did not flag it,
    in package (importance) order."""
    by_attr = {a.attribute: a for a in assessments}
    out: list[RequirementCandidate] = []
    for pkg in packages:
        a = by_attr.get(pkg.attribute)
        if a is None or a.assessment not in rules.candidates.assessments:
            continue
        if a.method == "rule" and not rules.candidates.from_rule_based:
            continue
        if a.guard_status == "flagged":
            continue
        c = _comparison(pkg)
        theme = _sub_theme(pkg, a.assessment)
        baseline, rationale = _baseline(pkg, c, theme)
        target = default_target(a.assessment, c, rules)
        facts = _customer_facts(pkg, a.assessment, rules.candidates.max_customer_facts)
        evidence = list(
            dict.fromkeys(
                [f.finding_id for f in pkg.ours]
                + (c.finding_ids if c else [])
                + [s.finding_id for s in facts]
                + [t.finding_id for t in pkg.trends]
                + a.cited_ids
            )
        )
        open_points = [p for p in pkg.coverage if p.startswith("missing")]
        open_points += [f"thin evidence: {render_fact(s)}" for s in facts if s.thin]
        if c is None:
            open_points.append("no comparable competitor value: the target cannot be derived")
        if a.assessment == "strength" and baseline != "known_present":
            open_points.append(
                "retain needs evidence of the current capability (ontology rule); baseline unknown"
            )
        label = label_of(pkg.attribute)
        candidate = RequirementCandidate(
            id=f"REQ-{len(out) + 1}",
            attribute=pkg.attribute,
            title=label + (f" · {theme.name}" if theme else ""),
            sub_theme=theme.name if theme else (a.what_exactly or None),
            assessment=a.assessment,
            change_intent=_intent(a.assessment, baseline),  # type: ignore[arg-type]
            baseline_status=baseline,  # type: ignore[arg-type]
            baseline_rationale=rationale,
            statement="",
            customer_value="",
            proposed_target=target,
            target=target,
            lower_is_better=c.lower_is_better if c else False,
            options=options_of(c),
            customer_facts=[render_fact(s) for s in facts],
            criterion=_criterion(label, target, evidence),
            evidence_ids=evidence,
            open_points=open_points,
            regions=list(brief.regions),
        )
        statement, value = template_wording(candidate)
        out.append(candidate.model_copy(update={"statement": statement, "customer_value": value}))
    return out


def apply_constraints(c: RequirementCandidate) -> RequirementCandidate:
    """Recompute target, intent and priority from the system's proposal plus the PM's constraints,
    in the order the PM gave them. Wording is reset to the template; the node may reword it."""
    target = c.proposed_target
    intent = _intent(c.assessment, c.baseline_status)
    priority = "normal"
    ours = next((o for o in c.options if o.label == "ours"), None)
    open_points = [p for p in c.open_points if not p.startswith("constraint:")]
    unit = (
        target.unit if target else (ours.unit if ours else (c.options[0].unit if c.options else ""))
    )
    condition = target.condition if target else (c.options[0].condition if c.options else "")
    op = "<=" if c.lower_is_better else ">="

    def pm_target(value: float, operator: str, rule: str) -> Target:
        return Target(
            operator=operator,  # type: ignore[arg-type]
            value=value,
            unit=unit,
            condition=condition,
            basis="human_set_target",
            rule=rule,
        )

    for k in c.constraints:
        reason = f": {k.reason}" if k.reason else ""
        if k.kind == "deprioritize":
            priority = "low"
        elif k.kind == "freeze":
            intent = "retain"
            if ours is not None:
                target = pm_target(ours.value, "=", f"PM: keep today's value{reason}")
            else:
                target = None
                open_points.append("constraint: freeze without a known current value")
        elif k.value is not None and k.kind == "set":
            target = pm_target(k.value, "=", f"PM: set{reason}")
        elif k.value is not None and k.kind in ("cap", "floor"):
            base = target.value if target is not None else k.value
            # cap limits ambition, floor raises it; "better" depends on the feature's direction
            if k.kind == "cap":
                value = _better(base, k.value, not c.lower_is_better)
            else:
                value = _better(base, k.value, c.lower_is_better)
            target = pm_target(value, op, f"PM {k.kind} {_fmt(k.value)}{reason}")
    label = label_of(c.attribute)
    updated = c.model_copy(
        update={
            "target": target,
            "change_intent": intent,
            "priority": priority,
            "open_points": open_points,
            "criterion": _criterion(label, target, c.evidence_ids),
            "wording": "template",
            "guard": [],
        }
    )
    statement, value = template_wording(updated)
    return updated.model_copy(update={"statement": statement, "customer_value": value})


def add_constraint(c: RequirementCandidate, constraint: Constraint) -> RequirementCandidate:
    return apply_constraints(c.model_copy(update={"constraints": [*c.constraints, constraint]}))


def facts_text(c: RequirementCandidate) -> str:
    """Everything the wording may draw numbers from."""
    lines = [c.title, c.baseline_rationale, *c.customer_facts]
    lines += [f"{o.label}: {_fmt(o.value)} {o.unit} {o.condition}" for o in c.options]
    if c.target is not None:
        lines.append(f"target {c.target.operator} {_fmt(c.target.value)} {c.target.unit}")
    return "\n".join(lines)


def wording_guard(
    c: RequirementCandidate, statement: str, customer_value: str, package_text: str
) -> list[GuardCheck]:
    text = f"{statement} {customer_value}"
    invented = unsupported_numbers(text, facts_text(c) + "\n" + package_text)
    checks = [
        GuardCheck(
            rule="numbers_from_facts",
            ok=not invented,
            detail=f"numbers not in the facts: {invented}" if invented else "",
        ),
        GuardCheck(
            rule="quantitative",
            ok=bool(numbers_in(statement)),
            detail="" if numbers_in(statement) else "the statement states no number",
        ),
    ]
    if c.target is not None:
        ok = number_in_text(c.target.value, statement, c.target.unit)
        checks.append(
            GuardCheck(
                rule="states_the_target",
                ok=ok,
                detail="" if ok else f"the statement must state the target {_fmt(c.target.value)}",
            )
        )
    return checks
