"""Citation and quantity checks (AGENT_SPEC §6.0.3–4).

Failing findings are dropped and counted, never repaired by an LLM. A quantity that cannot be traced
to a structured record, a code computation or the cited excerpt text is removed; the qualitative claim
stays with lowered confidence.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

from src.models.evidence import AgentName, AgentReport, Confidence, Finding, Source

_NUM = re.compile(r"(?<![\w.])-?\d+(?:[   .,']\d{3})*(?:[.,]\d+)?")
_LOWER: dict[Confidence, Confidence] = {"high": "medium", "medium": "low", "low": "low"}


def _candidates(token: str) -> set[float]:
    """All plausible readings of a number token ("1,234.5", "1.234,5", "1 234", "0,5")."""
    token = token.replace(" ", " ").replace(" ", " ").replace("'", " ")
    out: set[float] = set()
    variants = {
        token.replace(" ", "").replace(",", ""),  # 1,234.5  -> 1234.5
        token.replace(" ", "").replace(".", "").replace(",", "."),  # 1.234,5 -> 1234.5
        token.replace(" ", "").replace(",", "."),  # 0,5 -> 0.5
    }
    for v in variants:
        try:
            out.add(float(v))
        except ValueError:
            continue
    return out


def numbers_in(text: str) -> set[float]:
    found: set[float] = set()
    for m in _NUM.finditer(text):
        found |= _candidates(m.group(0))
    return found


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def number_in_text(value: float, text: str, unit: str = "") -> bool:
    """True if `value` (or its percent form for shares) is written in `text`."""
    targets = [value]
    if unit in {"share", "%", "percent"}:
        targets += [value * 100, value / 100]
    nums = numbers_in(text)
    return any(_close(t, n) for t in targets for n in nums)


def _quantity_supported(finding: Finding, cited: list[Source]) -> bool:
    q = finding.quantity
    assert q is not None
    if q.origin == "record":
        return any(s.kind in {"ontology", "sql"} and number_in_text(q.value, s.excerpt, q.unit) for s in cited)
    if q.origin == "computed":
        return any(s.kind in {"ontology", "sql", "feedback"} for s in cited)
    return any(number_in_text(q.value, s.excerpt, q.unit) for s in cited)


def check_finding(finding: Finding, sources: dict[str, Source]) -> tuple[Finding | None, bool]:
    """Return (finding or None if dropped, quantity_was_dropped)."""
    if not finding.claim.strip() or not finding.source_ids:
        return None, False
    cited = [sources.get(sid) for sid in finding.source_ids]
    if any(s is None or not s.excerpt.strip() for s in cited):
        return None, False
    if finding.quantity is not None and not _quantity_supported(finding, cited):  # type: ignore[arg-type]
        return finding.model_copy(update={"quantity": None, "confidence": _LOWER[finding.confidence]}), True
    return finding, False


def validate_findings(findings: Iterable[Finding], sources: Iterable[Source]) -> tuple[list[Finding], int, int]:
    """Return (kept findings, dropped findings, dropped quantities)."""
    by_id = {s.id: s for s in sources}
    kept: list[Finding] = []
    dropped = dropped_q = 0
    for f in findings:
        checked, q_dropped = check_finding(f, by_id)
        if checked is None:
            dropped += 1
            continue
        dropped_q += int(q_dropped)
        kept.append(checked)
    return kept, dropped, dropped_q


def validate_report(report: AgentReport) -> AgentReport:
    """Idempotent final check used by `collect`; adds to the report's drop counters."""
    findings = [f for f in report.findings if f.agent == report.agent]
    wrong_agent = len(report.findings) - len(findings)
    kept, dropped, dropped_q = validate_findings(findings, report.sources)
    stats = dict(report.stats)
    stats["dropped_findings"] = int(stats.get("dropped_findings", 0)) + dropped + wrong_agent
    stats["dropped_quantities"] = int(stats.get("dropped_quantities", 0)) + dropped_q
    return report.model_copy(update={"findings": kept, "stats": stats})


def assign_ids(agent: AgentName, findings: list[Finding]) -> list[Finding]:
    return [f.model_copy(update={"id": f"F-{agent}-{i}", "agent": agent}) for i, f in enumerate(findings, 1)]


def claim_numbers_supported(claim: str, cited: list[Source]) -> bool:
    """Every number written in an LLM-authored claim must appear in a cited excerpt."""
    text = " ".join(s.excerpt for s in cited)
    nums = numbers_in(text)
    for m in _NUM.finditer(claim):
        if not any(_close(c, n) for c in _candidates(m.group(0)) for n in nums):
            return False
    return True


def sentence_supported(text: str, cited_ids: list[str], allowed_ids: set[str], context_text: str) -> bool:
    """Check one explanation sentence: it cites only allowed ids and invents no numbers."""
    if not text.strip() or not cited_ids or any(cid not in allowed_ids for cid in cited_ids):
        return False
    context_nums = numbers_in(context_text)
    for m in _NUM.finditer(text):
        cands = _candidates(m.group(0))
        if not any(_close(c, n) for c in cands for n in context_nums):
            return False
    return True
