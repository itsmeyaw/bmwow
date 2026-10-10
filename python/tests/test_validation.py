from datetime import UTC, datetime

from bmwow.agent.models.evidence import AgentReport, Finding, Quantity, Source
from bmwow.agent.validation import (
    claim_numbers_supported,
    number_in_text,
    sentence_supported,
    validate_findings,
    validate_report,
)

NOW = datetime.now(UTC)


def src(id_, excerpt, kind="web"):
    return Source(id=id_, kind=kind, ref=id_, excerpt=excerpt, retrieved_at=NOW)


def finding(source_ids, quantity=None, confidence="high", agent="competition"):
    return Finding(
        id="",
        agent=agent,
        attribute="real_world_range",
        claim="Competitor has long range.",
        polarity="neutral",
        subject="Competitor A",
        quantity=quantity,
        source_ids=source_ids,
        confidence=confidence,
    )


SOURCES = [
    src("web:aaaa0001", "WLTP range of 1.234,5 km and 10-80% in 25 min."),
    src("kg:av-1", "Competitor A: real_world_range = 520 km (WLTP)", kind="ontology"),
    src("web:empty001", "   "),
]


def test_drops_dangling_and_empty_citations():
    kept, dropped, _ = validate_findings(
        [
            finding(["web:aaaa0001"]),
            finding(["web:missing1"]),
            finding(["web:aaaa0001", "web:missing1"]),
            finding(["web:empty001"]),
            finding([]),
        ],
        SOURCES,
    )
    assert len(kept) == 1 and dropped == 4


def test_unsupported_quantity_is_removed_and_confidence_lowered():
    q_bad = Quantity(value=610, unit="km", qualifier="WLTP")
    kept, dropped, dropped_q = validate_findings([finding(["web:aaaa0001"], q_bad)], SOURCES)
    assert dropped == 0 and dropped_q == 1
    assert kept[0].quantity is None and kept[0].confidence == "medium" and kept[0].claim


def test_supported_quantities_survive():
    ok_web = Quantity(value=1234.5, unit="km")  # European number format in the excerpt
    ok_min = Quantity(value=25, unit="min", qualifier="10-80%")
    ok_rec = Quantity(value=520, unit="km", origin="record")
    kept, _, dropped_q = validate_findings(
        [
            finding(["web:aaaa0001"], ok_web),
            finding(["web:aaaa0001"], ok_min),
            finding(["kg:av-1"], ok_rec),
        ],
        SOURCES,
    )
    assert dropped_q == 0 and all(f.quantity for f in kept)


def test_record_quantity_needs_a_structured_source():
    rec_from_web = Quantity(value=25, unit="min", origin="record")
    kept, _, dropped_q = validate_findings([finding(["web:aaaa0001"], rec_from_web)], SOURCES)
    assert dropped_q == 1 and kept[0].quantity is None


def test_computed_quantity_needs_stored_data():
    computed = Quantity(value=0.42, unit="share", origin="computed")
    _, _, dq_web = validate_findings([finding(["web:aaaa0001"], computed)], SOURCES)
    _, _, dq_kg = validate_findings([finding(["kg:av-1"], computed)], SOURCES)
    assert dq_web == 1 and dq_kg == 0


def test_validate_report_counts_and_is_idempotent():
    report = AgentReport(
        agent="competition",
        status="ok",
        sources=SOURCES,
        findings=[
            finding(["web:aaaa0001"]),
            finding(["web:nope0000"]),
            finding(["web:aaaa0001"], agent="trends"),
        ],
    )
    once = validate_report(report)
    twice = validate_report(once)
    assert len(once.findings) == 1 and once.stats["dropped_findings"] == 2
    assert twice.stats["dropped_findings"] == 2 and len(twice.findings) == 1


def test_number_helpers():
    assert number_in_text(0.23, "23% of buyers", unit="share")
    assert number_in_text(1200, "1,200 new chargers")
    assert not number_in_text(999, "range of 575 km")
    assert claim_numbers_supported("Range is 575 km.", [src("web:x", "WLTP range of 575 km")])
    assert not claim_numbers_supported("Range is 999 km.", [src("web:x", "WLTP range of 575 km")])


def test_sentence_supported():
    allowed = {"F-feedback-1", "fb:fb-0001"}
    ctx = "[F-feedback-1] weight: 16.2%"
    assert sentence_supported("16.2% of customers mention range.", ["F-feedback-1"], allowed, ctx)
    assert not sentence_supported("Range matters.", ["F-other-9"], allowed, ctx)
    assert not sentence_supported("Range matters.", [], allowed, ctx)
    assert not sentence_supported("40% mention range.", ["F-feedback-1"], allowed, ctx)
