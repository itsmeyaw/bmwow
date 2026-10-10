"""Cross-layer contracts retain wire semantics while sharing canonical vocabulary."""

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from bmwow.agent.models.evidence import Availability, Confidence, Finding, SearchLocale, Source
from bmwow.knowledge.config import SearchLocale as ConfiguredSearchLocale
from bmwow.knowledge.records import AttributeValue, FeedbackClassification
from bmwow.knowledge.types import SearchLocale as LocaleRecord
from bmwow.ontology.models import (
    AssessedConfidenceLevel,
    CapabilityAvailability,
    ExtractionConfidence,
    Signal,
    SqlLocator,
)


def test_locale_fields_have_one_owner_and_preserve_boundary_policies():
    assert SearchLocale is LocaleRecord
    payload = {"country": "de", "lang": "en"}
    configured = ConfiguredSearchLocale.model_validate(payload)
    assert SearchLocale.model_validate(configured).model_dump() == payload
    assert SearchLocale.model_validate({**payload, "future_field": True}).model_dump() == payload
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ConfiguredSearchLocale.model_validate({**payload, "future_field": True})


@pytest.mark.parametrize("availability", get_args(CapabilityAvailability))
def test_capability_vocabulary_survives_projection_and_analysis(availability):
    # Every graph availability state must survive the read and analysis wire boundaries.
    value = AttributeValue(
        node_id="signal:synthetic",
        attribute="parking",
        value="available",
        availability=availability,
    )
    source = Source(
        id="kg:signal:synthetic",
        kind="ontology",
        ref=value.node_id,
        excerpt="Synthetic capability.",
        retrieved_at="2026-10-11T00:00:00Z",
        availability=value.availability,
    )
    assert Source.model_validate_json(source.model_dump_json()).availability == availability


@pytest.mark.parametrize(
    ("field", "invalid"), [("availability", "probably"), ("epistemic_status", "verified")]
)
def test_unknown_ontology_qualifications_are_not_accepted_as_free_text(field, invalid):
    with pytest.raises(ValidationError, match="literal_error"):
        AttributeValue(
            node_id="signal:synthetic", attribute="parking", value="x", **{field: invalid}
        )
    with pytest.raises(ValidationError, match="literal_error"):
        Source(
            id="kg:signal:synthetic",
            kind="ontology",
            ref="signal:synthetic",
            excerpt="Synthetic capability.",
            retrieved_at="2026-10-11T00:00:00Z",
            **{field: invalid},
        )


def test_unavailable_data_does_not_supply_a_capability_status():
    assert Availability(source="catalog", status="unavailable").status == "unavailable"
    with pytest.raises(ValidationError, match="literal_error"):
        Availability(source="catalog", status="optional")
    with pytest.raises(ValidationError, match="literal_error"):
        AttributeValue(
            node_id="signal:synthetic", attribute="parking", value="x", availability="ok"
        )


def _finding(**updates):
    return Finding(
        id="F-feedback-1",
        agent="feedback",
        attribute="seat_comfort",
        claim="Customers want more comfortable seats.",
        polarity="demand",
        subject="customers",
        source_ids=["fb:evidence:synthetic"],
        **updates,
    )


def test_assessed_confidence_is_shared_but_unassessed_is_not_fabricated():
    assert Confidence is AssessedConfidenceLevel
    assert _finding(confidence="low").confidence == "low"
    assert ExtractionConfidence(level="unassessed", reason="Not assessed.").level == "unassessed"
    with pytest.raises(ValidationError, match="literal_error"):
        _finding(confidence="unassessed")


def test_demand_is_analysis_intent_and_cannot_be_cast_to_graph_sentiment(bundle):
    assert _finding(confidence="medium").polarity == "demand"
    signal = next(node for node in bundle.nodes if isinstance(node, Signal))
    wire = signal.model_dump(mode="json")
    wire["properties"]["sentiment"] = "demand"
    with pytest.raises(ValidationError, match="literal_error"):
        Signal.model_validate_json(json.dumps(wire))


def test_legacy_vfc_names_have_clear_accessors_without_changing_wire_fields():
    classification = FeedbackClassification(
        feedback_type="Wants",
        vfc_category="Seat ventilation",
        vfc_issue="Customer request",
        vfc_combined=None,
        attribute=None,
        mapping_status="proposed",
        locator=SqlLocator(
            kind="sql",
            table="public.feedback_aspects",
            record_key="synthetic",
            original_locator=None,
        ),
    )
    assert classification.aspect_term == "Seat ventilation"
    assert classification.aspect_label == "Customer request"
    payload = classification.model_dump(mode="json")
    assert payload["vfc_category"] == classification.aspect_term
    assert payload["vfc_issue"] == classification.aspect_label
    assert "aspect_term" not in payload and "aspect_label" not in payload
