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

from pydantic import BaseModel

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

from .rules import Rules, is_lower_better, load_rules, powertrain_of
from .sources import clip
from .stats import distribution, rank_position, relative_difference
from .validation import unsupported_numbers

SIGNIFICANT = 0.05


def label_of(attribute: str) -> str:
    return attribute.removeprefix("unmapped:").replace("_", " ")


_UNITS = {
    "kilometres": "km",
    "kilometers": "km",
    "kilometre": "km",
    "kilometer": "km",
    "minutes": "min",
    "minute": "min",
    "mins": "min",
    "€": "eur",
    "euro": "eur",
    "euros": "eur",
    "$": "usd",
    "us$": "usd",
    "dollars": "usd",
    "litres": "l",
    "liters": "l",
    "litre": "l",
    "liter": "l",
    "cubic feet": "cu ft",
    "cu.ft.": "cu ft",
    "cu. ft.": "cu ft",
    "cu.ft": "cu ft",
    "ft3": "cu ft",
    "inches": "inch",
    "in": "inch",
    '"': "inch",
    "horsepower": "hp",
    "bhp": "hp",
    "kwh/100km": "kwh/100 km",
    "speakers": "speakers",
    "loudspeakers": "speakers",
    "zones": "zone",
    "seconds": "s",
    "sec": "s",
    "secs": "s",
    "£": "gbp",
    "gbp": "gbp",
}
_MIN_SEC = re.compile(r"^(?:m|min)\s*(\d{1,2})\s*s$")  # "19 m 38 s" read as value 19, unit "m 38 s"


def normalize_unit(unit: str) -> str:
    u = unit.strip().lower()
    return _UNITS.get(u, u)


def normalize_quantity(value: float, unit: str) -> tuple[float, str]:
    """Same unit, same spelling; '<min> m <sec> s' becomes minutes. No cross-unit conversion: US cubic
    feet (SAE) and EU litres (VDA) are measured differently and stay apart."""
    m = _MIN_SEC.match(unit.strip().lower())
    if m:
        return round(value + int(m.group(1)) / 60, 2), "min"
    return value, normalize_unit(unit)


def _charge_time_unit(unit: str, condition: str) -> str:
    """A charging time written as "21 m" for a 10-80% window means minutes, not metres."""
    return "min" if unit == "m" and re.search(r"\d+-\d+%", condition) else unit


def normalize_condition(text: str) -> str:
    """Same test standard, same key: "10% to 80%" == "10-80%", case and spacing ignored."""
    t = text.lower()
    t = re.sub(
        r"(\d+)\s*%?\s*(?:capacity|soc|state of charge|charge)?\s*(?:to|-|–|—)\s*(\d+)\s*%",
        r"\1-\2%",
        t,
    )
    return re.sub(r"\s+", " ", t).strip(" ;,")


def _condition(finding: Finding, sources: dict[str, Source]) -> str:
    """The comparison key of a value: test standard (the ontology's measurement wins over the
    free-text qualifier) plus the powertrain. Trim variants and the region are not part of it, but
    an EV value is never compared with a plug-in hybrid or combustion one."""
    standard = ""
    for sid in finding.source_ids:
        m = sources[sid].measurement if sid in sources else None
        if m is not None and m.test_standard:
            # Free-text footnote conditions stay in the fact text; they are not a matching key.
            standard = m.test_standard
            break
    q = finding.quantity.qualifier if finding.quantity else ""
    parts = [x.strip() for x in re.sub(r"\bhorizon \S+", "", q).split(";")]
    if not standard:
        standard = "; ".join(
            x
            for x in parts
            if x and not x.lower().startswith(("variant ", "powertrain ")) and x != finding.region
        )
    pt = next((x.split()[1] for x in parts if x.lower().startswith("powertrain ")), None)
    variant = next((x for x in parts if x.lower().startswith("variant ")), "")
    pt = pt or powertrain_of(variant) or powertrain_of(parts[0]) or powertrain_of(finding.subject)
    return normalize_condition("; ".join(x for x in (standard, pt or "") if x))


def _fmt(value: float) -> str:
    return f"{value:g}"


def _value_comparisons(
    attribute: str,
    competitor: list[Finding],
    ours: list[Finding],
    sources: dict[str, Source],
    rules: Rules,
) -> list[ValueComparison]:
    groups: dict[tuple[str, str, str | None], list[tuple[Finding, float]]] = defaultdict(list)
    for f in competitor:
        if f.quantity is not None and f.quantity.unit and f.quantity.origin != "computed":
            value, unit = normalize_quantity(f.quantity.value, f.quantity.unit)
            condition = _condition(f, sources)
            unit = _charge_time_unit(unit, condition)
            groups[(unit, condition, f.region)].append((f, value))
    own: dict[tuple[str, str], float] = {}  # our best variant per unit and condition
    for f in ours:
        if f.quantity is not None and f.quantity.unit and f.quantity.origin == "record":
            value, unit = normalize_quantity(f.quantity.value, f.quantity.unit)
            condition = _condition(f, sources)
            unit = _charge_time_unit(unit, condition)
            key = (unit, condition)
            better = min if is_lower_better(attribute, unit) else max
            own[key] = better(own.get(key, value), value)
    out: list[ValueComparison] = []
    for (unit, condition, region), findings in sorted(groups.items(), key=lambda kv: str(kv[0])):
        # One value per competitor: several pages (or trims) of one model must not outweigh the
        # others, so each competitor contributes the median of its values; n counts competitors.
        per_competitor: dict[str, list[float]] = defaultdict(list)
        for f, v in findings:
            per_competitor[f.subject].append(v)
        values = [m.median for vs in per_competitor.values() if (m := distribution(vs))]
        d = distribution(values)
        if d is None:
            continue
        lower = is_lower_better(attribute, unit)
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
            finding_ids=[f.id for f, _ in findings],
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
            p = "p<0.001" if (s.p_value or 0) < 0.001 else f"p={s.p_value:.2g}"
            line += f" Significantly different from {s.differs_from} ({p})."
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
            source_ids=sorted(
                {sid for fs in found.values() for f in fs for sid in f.source_ids}
                | {sid for t in sub_themes if t.attribute == attribute for sid in t.source_ids}
            ),
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


class RuleResult(BaseModel):
    assessment: str  # gap | strength | hygiene_factor | demand | unclear
    basis: str  # "competitor + customers" | "customers only" | "trend only" | "thin"
    reasoning: str
    cited_ids: list[str]


def _pooled(pkg: EvidencePackage, direction: str) -> CustomerSignal | None:
    """The customer share across all requested regions (else the largest sample)."""
    signals = [s for s in pkg.customers if s.direction == direction]
    pooled = [s for s in signals if s.region is None] or signals
    return max(pooled, key=lambda s: s.n) if pooled else None


def rule_assessment(pkg: EvidencePackage, rules: Rules) -> RuleResult:
    """Assessment from computed facts only (no LLM). Customer shares count by the lower bound of
    their 95% interval; a comparison counts only with our own value in it (same unit, standard and
    powertrain). Missing views lower the certainty, they do not make a feature unclear."""
    t, ts = rules.structure.rule_min_signal, rules.structure.rule_min_strength
    p, r, s = (_pooled(pkg, d) for d in ("problem", "request", "strength"))
    pl, rl, sl = (x.ci_low if x else 0.0 for x in (p, r, s))
    c = next((v for v in pkg.competitor_values if v.ours is not None and v.field_size), None)

    def fmt(x: CustomerSignal | None, what: str) -> str:
        return (
            f"{x.share:.1%} {what} ({x.k} of {x.n}, CI {x.ci_low:.1%}–{x.ci_high:.1%})" if x else ""
        )

    def ids(*xs: CustomerSignal | None) -> list[str]:
        return [x.finding_id for x in xs if x is not None]

    if c is not None:
        worse = (c.ours_vs_median or 0) > 0 if c.lower_is_better else (c.ours_vs_median or 0) < 0
        where = (
            f"ours {_fmt(c.ours)} {c.unit} vs competitor median {_fmt(c.median)} "
            f"({c.condition or 'same basis'}, rank {c.ours_rank} of {c.field_size})"
        )
        if worse and max(pl, rl) >= t:
            x = p if pl >= rl else r
            return RuleResult(
                assessment="gap",
                basis="competitor + customers",
                reasoning=f"We trail: {where}; customers: {fmt(x, x.direction if x else '')}.",
                cited_ids=[*c.finding_ids, *ids(x)],
            )
        if not worse and pl >= t:
            return RuleResult(
                assessment="hygiene_factor",
                basis="competitor + customers",
                reasoning=f"Customers complain ({fmt(p, 'problem')}) though we do not trail: {where}.",
                cited_ids=[*c.finding_ids, *ids(p)],
            )
        if c.ours_rank == 1 and (sl >= t or max(pl, rl) < t):
            return RuleResult(
                assessment="strength",
                basis="competitor + customers",
                reasoning=f"We lead: {where}" + (f"; customers: {fmt(s, 'praise')}." if s else "."),
                cited_ids=[*c.finding_ids, *ids(s)],
            )
    if sl >= ts and sl > max(pl, rl):
        return RuleResult(
            assessment="strength",
            basis="customers only",
            reasoning=f"Customers praise it ({fmt(s, 'praise')}) more than they report problems or "
            "wishes; no comparable competitor value with ours.",
            cited_ids=ids(s, p),
        )
    if rl >= t and rl >= pl:
        return RuleResult(
            assessment="demand",
            basis="customers only",
            reasoning=f"Customers ask for it ({fmt(r, 'request')}); no comparable competitor value.",
            cited_ids=ids(r),
        )
    if pl >= t:
        return RuleResult(
            assessment="gap",
            basis="customers only",
            reasoning=f"Customers report problems ({fmt(p, 'problem')}): the current model falls "
            "short of what customers expect; no comparable competitor value.",
            cited_ids=ids(p),
        )
    demand_trends = [x for x in pkg.trends if x.polarity == "demand" and not x.thin]
    if demand_trends and not pkg.customers:
        return RuleResult(
            assessment="demand",
            basis="trend only",
            reasoning=f"A demand trend applies: {demand_trends[0].claim}",
            cited_ids=[demand_trends[0].finding_id],
        )
    shares = [x for x in (p, r, s) if x is not None]
    return RuleResult(
        assessment="unclear",
        basis="thin",
        reasoning=(
            "All customer shares are below the threshold "
            f"({', '.join(fmt(x, x.direction) for x in shares)})."
            if shares
            else "No customer signal and no comparison with our value."
        ),
        cited_ids=ids(*shares),
    )


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
    rule = rule_assessment(pkg, load_rules())
    lines += [
        "",
        "## Rule-based suggestion (computed by code from the facts above)",
        f"- {rule.assessment} (basis: {rule.basis}): {rule.reasoning}",
    ]
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
    invented = unsupported_numbers(text, rendered)
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
