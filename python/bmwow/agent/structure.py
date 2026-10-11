"""structure_agent's deterministic parts: assemble evidence packages and guard judgments.

`assemble` turns the four validated reports into one evidence package per feature: facts with their
finding ids, comparable competitor values next to ours, customer shares with intervals, sub-themes,
trends, quotes (including counter-evidence) and coverage notes. It computes facts, never verdicts.

`guard` checks an LLM judgment against its package: cited ids exist, numbers appear in the package,
and every assessment rests on the kind of evidence it claims.
"""

from __future__ import annotations

import re
from collections import defaultdict

from bmwow.agent.models.evidence import (
    AgentName,
    AgentReport,
    CustomerSignal,
    Direction,
    EvidencePackage,
    FactRef,
    Finding,
    GuardCheck,
    ProductBrief,
    Quote,
    Source,
    TrendSignal,
    ValueComparison,
)

from .rules import Rules
from .sources import clip
from .stats import distribution, rank_position, relative_difference
from .validation import numbers_in

SIGNIFICANT = 0.05


def label_of(attribute: str) -> str:
    return attribute.removeprefix("unmapped:").replace("_", " ")


def _condition(finding: Finding, sources: dict[str, Source]) -> str:
    """The comparison condition (test standard and constraints) of a value; the ontology's
    measurement wins over the free-text qualifier."""
    for sid in finding.source_ids:
        m = sources[sid].measurement if sid in sources else None
        if m is not None and (m.test_standard or m.conditions):
            return "; ".join(x for x in [m.test_standard or "", *m.conditions] if x)
    q = finding.quantity.qualifier if finding.quantity else ""
    q = re.sub(r"\bhorizon \S+", "", q)
    if finding.region:
        q = re.sub(rf"\b{re.escape(finding.region)}\b", "", q)
    return re.sub(r"\s+", " ", q).strip(" ;,")


def _fmt(value: float) -> str:
    return f"{value:g}"


def _value_comparisons(
    attribute: str,
    competitor: list[Finding],
    ours: list[Finding],
    sources: dict[str, Source],
    rules: Rules,
) -> list[ValueComparison]:
    lower = attribute in rules.structure.lower_is_better
    groups: dict[tuple[str, str, str | None], list[Finding]] = defaultdict(list)
    for f in competitor:
        if f.quantity is not None and f.quantity.unit and f.quantity.origin != "computed":
            key = (f.quantity.unit.strip().lower(), _condition(f, sources).lower(), f.region)
            groups[key].append(f)
    own: dict[tuple[str, str], float] = {}
    for f in ours:
        if f.quantity is not None and f.quantity.unit and f.quantity.origin == "record":
            own.setdefault(
                (f.quantity.unit.strip().lower(), _condition(f, sources).lower()), f.quantity.value
            )
    out: list[ValueComparison] = []
    for (unit, condition, region), findings in sorted(groups.items(), key=lambda kv: str(kv[0])):
        values = [f.quantity.value for f in findings if f.quantity is not None]
        d = distribution(values)
        if d is None:
            continue
        mine = own.get((unit, condition))
        if mine is None and (unit, "") in own and not condition:
            mine = own[(unit, "")]
        comparison = ValueComparison(
            unit=unit,
            condition=condition,
            region=region,
            n=d.n,
            minimum=d.minimum,
            median=d.median,
            maximum=d.maximum,
            lower_is_better=lower,
            finding_ids=[f.id for f in findings],
        )
        if mine is not None:
            rank, size = rank_position(mine, values, higher_is_better=not lower)
            diff = relative_difference(mine, d.median)
            comparison = comparison.model_copy(
                update={
                    "ours": mine,
                    "ours_rank": rank,
                    "field_size": size,
                    "ours_vs_median": round(diff, 4) if diff is not None else None,
                }
            )
        out.append(comparison)
    return out


def _customer_signal(f: Finding) -> CustomerSignal | None:
    if f.stats is None or f.direction is None or f.quantity is None:
        return None
    test = f.stats.region_test
    significant = test is not None and test.p_value < SIGNIFICANT
    return CustomerSignal(
        finding_id=f.id,
        direction=f.direction,
        region=f.region,
        share=f.quantity.value,
        k=f.stats.k,
        n=f.stats.n,
        ci_low=f.stats.ci_low,
        ci_high=f.stats.ci_high,
        thin=f.stats.thin,
        differs_from=test.other if significant and test else None,
        p_value=test.p_value if test else None,
    )


def _comparisons(pkg: EvidencePackage) -> list[str]:
    lines: list[str] = []
    for c in pkg.competitor_values:
        where = f", {c.region}" if c.region else ""
        cond = f" ({c.condition}{where})" if c.condition or where else ""
        head = (
            f"Competitors{cond}: median {_fmt(c.median)} {c.unit}, range {_fmt(c.minimum)}–"
            f"{_fmt(c.maximum)} {c.unit}, n={c.n}; {'lower' if c.lower_is_better else 'higher'} is better."
        )
        if c.ours is not None and c.ours_vs_median is not None:
            head += (
                f" Ours: {_fmt(c.ours)} {c.unit}, {c.ours_vs_median:+.1%} vs the median, "
                f"rank {c.ours_rank} of {c.field_size}."
            )
        elif c.ours is None:
            head += " No comparable value of ours."
        lines.append(head)
    for s in pkg.customers:
        where = s.region or "all requested regions"
        line = (
            f"Customers, {where}: {s.direction} {s.share:.1%} ({s.k} of {s.n}, 95% CI "
            f"{s.ci_low:.1%}–{s.ci_high:.1%}){', thin sample' if s.thin else ''}."
        )
        if s.differs_from:
            line += f" Significantly different from {s.differs_from} (p={s.p_value:.2g})."
        lines.append(line)
    for t in pkg.trends:
        lines.append(
            f"Trend ({t.polarity}, horizon {t.horizon or 'unknown'}, "
            f"{t.n_independent_sources or 0} independent source(s){', thin' if t.thin else ''}): "
            f"{t.claim}"
        )
    return lines


def _quotes(customer: list[Finding], sources: dict[str, Source], limit: int) -> list[Quote]:
    """Representative quotes, alternating directions so counter-evidence is included."""
    by_direction: dict[Direction | None, list[str]] = defaultdict(list)
    order: list[Direction | None] = ["problem", "request", "strength", "neutral", None]
    for f in sorted(customer, key=lambda f: -f.weight):
        for sid in f.source_ids:
            if sid not in by_direction[f.direction]:
                by_direction[f.direction].append(sid)
    out: list[Quote] = []
    seen: set[str] = set()
    while len(out) < limit and any(by_direction.get(d) for d in order):
        for d in order:
            queue = by_direction.get(d, [])
            while queue and queue[0] in seen:
                queue.pop(0)
            if queue and len(out) < limit and queue[0] in sources:
                sid = queue.pop(0)
                seen.add(sid)
                out.append(Quote(source_id=sid, direction=d, text=clip(sources[sid].excerpt, 300)))
            elif queue:
                queue.pop(0)
    return out


def assemble(
    reports: dict[AgentName, AgentReport], brief: ProductBrief, rules: Rules
) -> list[EvidencePackage]:
    sources: dict[str, Source] = {s.id: s for r in reports.values() for s in r.sources}
    by_attr: dict[str, dict[AgentName, list[Finding]]] = defaultdict(lambda: defaultdict(list))
    for agent, report in reports.items():
        for f in report.findings:
            by_attr[f.attribute][agent].append(f)
    sub_themes = [t for r in reports.values() for t in r.sub_themes]
    notes = [
        f"{report.agent} · {a.source}: {a.status}{' — ' + a.reason if a.reason else ''}"
        for report in reports.values()
        for a in report.availability
        if a.status != "ok"
    ]
    packages: list[EvidencePackage] = []
    for attribute, found in by_attr.items():
        ours, competitor = found.get("baseline", []), found.get("competition", [])
        customer, trend = found.get("feedback", []), found.get("trends", [])
        values = _value_comparisons(attribute, competitor, ours, sources, rules)
        valued = {i for v in values for i in v.finding_ids}
        customers = [s for s in (_customer_signal(f) for f in customer) if s is not None]
        pkg = EvidencePackage(
            attribute=attribute,
            label=label_of(attribute),
            importance=max(
                (s.ci_low for s in customers if s.direction in ("problem", "request")), default=0.0
            ),
            ours=[
                FactRef(finding_id=f.id, agent="baseline", subject=f.subject, text=f.claim)
                for f in ours
            ],
            competitor_values=values,
            competitor_facts=[
                FactRef(finding_id=f.id, agent="competition", subject=f.subject, text=f.claim)
                for f in competitor
                if f.id not in valued
            ],
            customers=customers,
            sub_themes=[t for t in sub_themes if t.attribute == attribute],
            trends=[
                TrendSignal(
                    finding_id=f.id,
                    claim=f.claim,
                    polarity=f.polarity,
                    horizon=f.horizon,
                    n_independent_sources=f.n_independent_sources,
                    thin=(f.n_independent_sources or 0) < 2,
                )
                for f in trend
            ],
            quotes=_quotes(customer, sources, rules.structure.max_quotes_per_package),
            finding_ids=[f.id for fs in found.values() for f in fs],
            source_ids=sorted({sid for fs in found.values() for f in fs for sid in f.source_ids}),
        )
        missing = [
            name
            for name, present in (
                ("our value", bool(ours)),
                ("competitor evidence", bool(competitor)),
                ("customer feedback", bool(customer)),
                ("trend evidence", bool(trend)),
            )
            if not present
        ]
        coverage = [f"missing: {', '.join(missing)}"] if missing else []
        packages.append(
            pkg.model_copy(update={"comparisons": _comparisons(pkg), "coverage": coverage + notes})
        )
    return sorted(packages, key=lambda p: (-p.importance, -len(p.finding_ids), p.attribute))


def gap_requests(
    packages: list[EvidencePackage], brief: ProductBrief, rules: Rules, known: set[str]
) -> list[str]:
    """Important features (customer problem/request share above the threshold) that have no
    competitor evidence at all: candidates for one targeted research round. Only taxonomy features of
    the active taxonomy (`known`) and only when the brief has competitors to research."""
    if not brief.competitors:
        return []
    wanted = [
        p.attribute
        for p in packages
        if p.attribute in known
        and p.importance >= rules.gap_fill.min_customer_ci_low
        and not p.competitor_values
        and not p.competitor_facts
    ]
    return wanted[: rules.gap_fill.max_features]


def render_package(pkg: EvidencePackage) -> str:
    """The package as text for the judgment, with every citable id."""
    lines = [f"# Feature: {pkg.label} ({pkg.attribute})", "", "## Facts computed by code"]
    lines += [f"- {c}" for c in (pkg.comparisons or _comparisons(pkg))] or ["- none"]
    lines += ["", "## Our current model"]
    lines += [f"- [{f.finding_id}] {f.text}" for f in pkg.ours] or ["- no evidence"]
    lines += ["", "## Competitors"]
    for v in pkg.competitor_values:
        lines.append(f"- values from: {', '.join(f'[{i}]' for i in v.finding_ids)}")
    lines += [f"- [{f.finding_id}] {f.subject}: {f.text}" for f in pkg.competitor_facts]
    if not pkg.competitor_values and not pkg.competitor_facts:
        lines.append("- no evidence")
    lines += ["", "## Customers"]
    lines += [
        f"- [{s.finding_id}] {s.direction}, {s.region or 'all requested regions'}: "
        f"{s.share:.1%} ({s.k} of {s.n}, CI {s.ci_low:.1%}–{s.ci_high:.1%}){', thin' if s.thin else ''}"
        for s in pkg.customers
    ] or ["- no evidence"]
    if pkg.sub_themes:
        lines += ["", "## What exactly customers mean (sub-themes)"]
        lines += [
            f"- {t.direction}: {t.name} — {t.k} of {t.of} items"
            f"{' in a sample' if t.method == 'llm' else ''} (e.g. {', '.join(t.source_ids)})"
            for t in pkg.sub_themes
        ]
    if pkg.quotes:
        lines += ["", "## Quotes (verbatim, incl. counter-evidence)"]
        lines += [f"- [{q.source_id}] ({q.direction}) {q.text}" for q in pkg.quotes]
    lines += ["", "## Trends"]
    lines += [f"- [{t.finding_id}] {t.claim}" for t in pkg.trends] or ["- no evidence"]
    lines += ["", "## Coverage"]
    lines += [f"- {c}" for c in pkg.coverage] or ["- all four views present"]
    return "\n".join(lines)


def guard(
    pkg: EvidencePackage,
    assessment: str,
    widespread: str,
    text: str,
    cited_ids: list[str],
    rules: Rules,
) -> list[GuardCheck]:
    """Rules that a judgment must satisfy; each check says why it failed."""
    known = set(pkg.finding_ids) | set(pkg.source_ids)
    cited = set(cited_ids)
    by_dir: dict[str, set[str]] = defaultdict(set)
    for s in pkg.customers:
        by_dir[s.direction].add(s.finding_id)
    value_ids = {i for v in pkg.competitor_values for i in v.finding_ids}
    better = {i for v in pkg.competitor_values if (v.ours_rank or 99) == 1 for i in v.finding_ids}
    competitor_ids = value_ids | {f.finding_id for f in pkg.competitor_facts}
    demand_trends = {t.finding_id for t in pkg.trends if t.polarity == "demand"}
    thin_ids = {s.finding_id for s in pkg.customers if s.thin} | {
        t.finding_id for t in pkg.trends if t.thin
    }
    rendered = render_package(pkg)
    unknown = sorted(cited - known)
    invented = sorted(numbers_in(text) - numbers_in(rendered))
    checks = [
        GuardCheck(
            rule="cited_ids_exist",
            ok=not unknown,
            detail=f"unknown ids: {unknown}" if unknown else "",
        ),
        GuardCheck(
            rule="cites_evidence",
            ok=assessment == "unclear" or bool(cited & known),
            detail="an assessment other than unclear must cite package ids",
        ),
        GuardCheck(
            rule="numbers_from_package",
            ok=not invented,
            detail=f"numbers not in the package: {invented}" if invented else "",
        ),
    ]
    if widespread == "widespread":
        ok = any(s.ci_low >= rules.structure.widespread_min_ci_low for s in pkg.customers)
        checks.append(
            GuardCheck(
                rule="widespread_supported",
                ok=ok,
                detail=f"no customer share with CI lower bound >= {rules.structure.widespread_min_ci_low:.0%}",
            )
        )
    needs = {
        "gap": (
            by_dir["problem"] | by_dir["request"] | competitor_ids,
            "a customer problem/request or competitor evidence",
        ),
        "strength": (
            by_dir["strength"] | better,
            "customer praise or a comparison where ours ranks first",
        ),
        "hygiene_factor": (by_dir["problem"], "a customer problem share"),
        "demand": (by_dir["request"] | demand_trends, "a customer request or a demand trend"),
    }
    if assessment in needs:
        ids, what = needs[assessment]
        checks.append(
            GuardCheck(
                rule=f"{assessment}_supported",
                ok=bool(cited & ids),
                detail=f"'{assessment}' must cite {what}",
            )
        )
    if cited & thin_ids:
        words = [w.lower() for w in rules.structure.thin_words]
        checks.append(
            GuardCheck(
                rule="thin_evidence_acknowledged",
                ok=any(w in text.lower() for w in words),
                detail="cites thin evidence without saying so",
            )
        )
    return [c if not c.ok else c.model_copy(update={"detail": ""}) for c in checks]
