"""Reject unsafe baseline, catalog, scope and metric reasoning in closed graphs."""

import copy
import json
from pathlib import Path

import pytest

from bmwow.ontology import validate_bundle

FIXTURE = Path(__file__).resolve().parents[3] / "contracts/ontology/examples/synthetic.json"


@pytest.fixture
def bundle():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert validate_bundle(data) == []
    return data


def node(bundle, node_id):
    return next(item for item in bundle["nodes"] if item["id"] == node_id)


def nodes_of(bundle, kind):
    return [item for item in bundle["nodes"] if item["type"] == kind]


def baseline(bundle):
    edge = next(item for item in bundle["edges"] if item["type"] == "BASELINED_ON")
    return node(bundle, edge["source_id"]), node(bundle, edge["target_id"])


def add_edge(bundle, relation, source, target, transfer=None):
    bundle["edges"].append(
        {
            "id": f"edge:test-{len(bundle['edges'])}",
            "type": relation,
            "source_id": source,
            "target_id": target,
            "rationale": "Synthetic test relationship.",
            "context_transfer": transfer,
        }
    )


def assert_invalid(bundle, message):
    errors = validate_bundle(bundle)
    assert errors
    assert any(message in error for error in errors), errors


def scalar_measurement():
    return {
        "metric": "response_share",
        "value": 0.25,
        "value_range": None,
        "unit": "proportion",
        "statistic": "proportion",
        "temporal_status": "historical",
        "period": None,
        "sample_size": None,
        "denominator": None,
        "scale": None,
        "comparison_basis": None,
        "population": None,
        "test_standard": None,
        "conditions": [],
        "question": None,
        "response_category": None,
        "notes": [],
    }


@pytest.mark.parametrize("location", ["evidence", "capability"])
@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("no_value", "exactly one scalar value or value_range"),
        ("two_values", "exactly one scalar value or value_range"),
        ("reversed_range", "range minimum exceeds maximum"),
        ("proportion", "proportion must be"),
        ("percent_range", "percent must be"),
        ("negative_count", "count must be a nonnegative integer"),
        ("fractional_count_range", "count must be a nonnegative integer"),
        ("range_outside_scale", "invalid measurement scale"),
        ("future_historical", "future measurements cannot be historical"),
        ("reversed_period", "period starts after it ends"),
    ],
)
def test_quantitative_rules_apply_to_original_and_capability_measurements(
    bundle, location, case, message
):
    measurement = scalar_measurement()
    match case:
        case "no_value":
            measurement["value"] = None
        case "two_values":
            measurement["value_range"] = {"minimum": 0.1, "maximum": 0.9}
        case "reversed_range":
            measurement["value"] = None
            measurement["value_range"] = {"minimum": 0.9, "maximum": 0.1}
        case "proportion":
            measurement["value"] = 1.1
        case "percent_range":
            measurement.update(value=None, statistic="percent", unit="percent")
            measurement["value_range"] = {"minimum": 10, "maximum": 110}
        case "negative_count":
            measurement.update(value=-1, statistic="count", unit="vehicles")
        case "fractional_count_range":
            measurement.update(value=None, statistic="count", unit="vehicles")
            measurement["value_range"] = {"minimum": 1, "maximum": 2.5}
        case "range_outside_scale":
            measurement.update(value=None, statistic="mean", unit="rating")
            measurement["value_range"] = {"minimum": 2, "maximum": 6}
            measurement["scale"] = {"minimum": 1, "maximum": 5}
        case "future_historical":
            measurement["period"] = {"label": "2199", "start": None, "end": None}
        case "reversed_period":
            measurement["period"] = {
                "label": "Synthetic period",
                "start": "2025-12-31",
                "end": "2025-01-01",
            }
    if location == "evidence":
        node(bundle, "evidence:fixture-customer")["properties"]["measurement"] = measurement
    else:
        node(bundle, "signal:fixture-competitor")["properties"]["capability"]["measurement"] = (
            measurement
        )
    assert_invalid(bundle, message)


@pytest.mark.parametrize("location", ["evidence", "capability"])
@pytest.mark.parametrize("interval", [False, True])
def test_zero_and_genuine_intervals_remain_valid(bundle, location, interval):
    measurement = scalar_measurement()
    if interval:
        measurement.update(value=None, value_range={"minimum": 0, "maximum": 0.25})
    else:
        measurement["value"] = 0
    if location == "evidence":
        node(bundle, "evidence:fixture-customer")["properties"]["measurement"] = measurement
    else:
        node(bundle, "signal:fixture-competitor")["properties"]["capability"]["measurement"] = (
            measurement
        )
    assert validate_bundle(bundle) == []


def test_partially_future_period_cannot_be_historical(bundle):
    measurement = scalar_measurement()
    measurement["period"] = {
        "label": "Synthetic extended period",
        "start": "2025-01-01",
        "end": "2199-12-31",
    }
    node(bundle, "evidence:fixture-customer")["properties"]["measurement"] = measurement
    assert_invalid(bundle, "future measurements cannot be historical")
    measurement["temporal_status"] = "source_reported_future"
    assert validate_bundle(bundle) == []


@pytest.mark.parametrize("field", ["country_codes", "engine_types"])
def test_country_and_engine_transfers_need_explanation(bundle, field):
    signal = node(bundle, "signal:fixture-customer")
    signal["properties"]["context"][field] = ["DE"] if field == "country_codes" else ["bev"]
    assert_invalid(bundle, "scope transfer requires an explicit explanation")


@pytest.mark.parametrize("kind", ["CustomerNeed", "Requirement"])
def test_reasoning_objects_need_retrievable_canonical_feature(bundle, kind):
    subject = nodes_of(bundle, kind)[0]
    bundle["edges"] = [
        edge
        for edge in bundle["edges"]
        if not (edge["type"] == "CONCERNS" and edge["source_id"] == subject["id"])
    ]
    assert_invalid(bundle, "needs at least one CONCERNS Feature")


def test_capability_claim_is_not_promoted_to_a_verified_fact(bundle):
    _, signal = baseline(bundle)
    signal["properties"]["epistemic_status"] = "reported_experience"
    assert_invalid(bundle, "publisher_claim epistemic status")


def test_noncapability_signal_cannot_smuggle_a_capability_payload(bundle):
    customer = node(bundle, "signal:fixture-customer")
    customer["properties"]["capability"] = copy.deepcopy(
        node(bundle, "signal:fixture-competitor")["properties"]["capability"]
    )
    assert_invalid(bundle, "only a capability Signal can contain a capability payload")


def test_private_feedback_cannot_smuggle_public_sampling_metadata(bundle):
    public = next(
        item
        for item in nodes_of(bundle, "Signal")
        if item["properties"]["signal_kind"] == "public_sentiment"
    )
    node(bundle, "signal:fixture-customer")["properties"]["public_context"] = copy.deepcopy(
        public["properties"]["public_context"]
    )
    assert_invalid(bundle, "only a public_sentiment Signal can contain public_context")


def test_one_capability_claim_describes_at_most_one_catalog_item(bundle):
    edge = next(edge for edge in bundle["edges"] if edge["type"] == "DESCRIBES")
    other = next(
        item for item in nodes_of(bundle, "CatalogItem") if item["id"] != edge["target_id"]
    )
    add_edge(bundle, "DESCRIBES", edge["source_id"], other["id"], "Synthetic scope transfer.")
    assert_invalid(bundle, "describes at most one CatalogItem")


@pytest.mark.parametrize("intent", ["improve", "retain", "remove"])
def test_existing_product_changes_need_present_baseline(bundle, intent):
    requirement, _ = baseline(bundle)
    requirement["properties"].update(change_intent=intent, baseline_status="unknown")
    assert_invalid(bundle, "requires a known_present baseline")


def test_introduction_is_not_redundant_with_known_present_feature(bundle):
    requirement, _ = baseline(bundle)
    requirement["properties"]["change_intent"] = "introduce"
    assert_invalid(bundle, "introduce cannot use a known_present baseline")


def test_missing_catalog_claim_does_not_prove_absence(bundle):
    requirement, _ = baseline(bundle)
    requirement["properties"].update(change_intent="introduce", baseline_status="known_absent")
    bundle["edges"] = [
        edge
        for edge in bundle["edges"]
        if not (edge["type"] == "BASELINED_ON" and edge["source_id"] == requirement["id"])
    ]
    assert_invalid(bundle, "known baseline status requires explicit BASELINED_ON evidence")


def test_known_absence_needs_explicit_unavailable_claim(bundle):
    requirement, _ = baseline(bundle)
    requirement["properties"].update(change_intent="introduce", baseline_status="known_absent")
    assert_invalid(bundle, "explicit unavailable capability evidence")


def test_announced_capability_does_not_prove_a_present_baseline(bundle):
    _, signal = baseline(bundle)
    signal["properties"]["capability"]["availability"] = "announced"
    assert_invalid(bundle, "known_present requires an explicitly available capability")


def test_explicit_absence_can_ground_an_introduction(bundle):
    requirement, signal = baseline(bundle)
    requirement["properties"].update(change_intent="introduce", baseline_status="known_absent")
    signal["properties"]["capability"]["availability"] = "unavailable"
    assert validate_bundle(bundle) == []


def test_unknown_baseline_is_explicit_and_does_not_imply_absence(bundle):
    requirement, _ = baseline(bundle)
    requirement["properties"].update(change_intent="introduce", baseline_status="unknown")
    bundle["edges"] = [
        edge
        for edge in bundle["edges"]
        if not (edge["type"] == "BASELINED_ON" and edge["source_id"] == requirement["id"])
    ]
    assert validate_bundle(bundle) == []


def test_competitor_claim_is_not_a_bmw_baseline(bundle):
    requirement, _ = baseline(bundle)
    for edge in bundle["edges"]:
        if edge["type"] == "BASELINED_ON" and edge["source_id"] == requirement["id"]:
            edge["target_id"] = "signal:fixture-competitor"
            edge["context_transfer"] = "Synthetic competitor transfer."
    assert_invalid(bundle, "must target a product_capability Signal")
    assert_invalid(bundle, "must describe the BMW baseline model or variant")


def test_baseline_must_share_the_requirements_feature(bundle):
    _, signal = baseline(bundle)
    other = copy.deepcopy(nodes_of(bundle, "Feature")[0])
    other.update(id="feature:test-unrelated", entity_key="feature:test-unrelated")
    bundle["nodes"].append(other)
    for edge in bundle["edges"]:
        if edge["type"] == "CONCERNS" and edge["source_id"] == signal["id"]:
            edge["target_id"] = other["id"]
    assert_invalid(bundle, "baseline must share a canonical Feature")


def test_variant_baseline_is_grounded_in_its_parent_model(bundle):
    requirement, signal = baseline(bundle)
    parent_id = requirement["properties"]["context"]["vehicle_model_ids"][0]
    variant = copy.deepcopy(node(bundle, parent_id))
    variant.update(id="vehicle:test-variant", entity_key="vehicle:test-variant")
    variant["properties"]["variant"] = "Synthetic test trim"
    bundle["nodes"].append(variant)
    add_edge(bundle, "IS_VARIANT_OF", variant["id"], parent_id)
    signal["properties"]["context"]["vehicle_model_ids"] = [variant["id"]]
    for edge in bundle["edges"]:
        if signal["id"] in (edge["source_id"], edge["target_id"]):
            edge["context_transfer"] = (
                "Synthetic variant-specific claim transferred to model family."
            )
    assert validate_bundle(bundle) == []
    bundle["edges"] = [
        edge
        for edge in bundle["edges"]
        if not (edge["type"] == "IS_VARIANT_OF" and edge["source_id"] == variant["id"])
    ]
    assert_invalid(bundle, "BMW baseline model or variant")


def test_capability_variant_must_agree_with_explicitly_scoped_model_variant(bundle):
    signal = next(
        item
        for item in nodes_of(bundle, "Signal")
        if item["properties"]["capability"]
        and item["properties"]["capability"]["variant"] is not None
        and any(
            node(bundle, model_id)["properties"]["variant"] is not None
            for model_id in item["properties"]["context"]["vehicle_model_ids"]
        )
    )
    signal["properties"]["capability"]["variant"] = "Different fictional trim"
    assert_invalid(bundle, "capability variant disagrees with the scoped model variant")


def test_general_model_can_keep_a_more_specific_variant_annotation(bundle):
    _, signal = baseline(bundle)
    assert all(
        node(bundle, model_id)["properties"]["variant"] is None
        for model_id in signal["properties"]["context"]["vehicle_model_ids"]
    )
    signal["properties"]["capability"]["variant"] = "Specific fictional trim from source text"
    assert validate_bundle(bundle) == []


@pytest.mark.parametrize("case", ["self", "wrong_generation", "two_parents", "parent_is_variant"])
def test_variant_relationship_invariants(bundle, case):
    edge = next(edge for edge in bundle["edges"] if edge["type"] == "IS_VARIANT_OF")
    variant, parent = node(bundle, edge["source_id"]), node(bundle, edge["target_id"])
    match case:
        case "self":
            edge["target_id"] = variant["id"]
            message = "cyclic variant ancestry"
        case "wrong_generation":
            variant["properties"]["generation_code"] = "SyntheticDifferentGeneration"
            message = "must share brand, line, and generation"
        case "two_parents":
            second = copy.deepcopy(parent)
            second.update(id="vehicle:test-second-parent", entity_key="vehicle:test-second-parent")
            bundle["nodes"].append(second)
            add_edge(bundle, "IS_VARIANT_OF", variant["id"], second["id"])
            message = "at most one parent model"
        case "parent_is_variant":
            parent["properties"]["variant"] = "Synthetic parent trim"
            message = "variant child and family parent"
    assert_invalid(bundle, message)


@pytest.mark.parametrize("kind", ["requires_all", "requires_any", "excludes"])
def test_logical_catalog_conditions_need_references(bundle, kind):
    item = nodes_of(bundle, "CatalogItem")[0]
    item["properties"]["conditions"] = [
        {"kind": kind, "catalog_item_ids": [], "description": "Synthetic condition."}
    ]
    assert_invalid(bundle, "condition 0 has invalid catalog item references")


@pytest.mark.parametrize("kind", ["configuration", "usage", "unknown"])
def test_textual_catalog_conditions_do_not_fabricate_item_references(bundle, kind):
    item, referenced = nodes_of(bundle, "CatalogItem")[:2]
    item["properties"]["conditions"] = [
        {
            "kind": kind,
            "catalog_item_ids": [referenced["id"]],
            "description": "Synthetic condition.",
        }
    ]
    assert_invalid(bundle, "condition 0 has invalid catalog item references")


@pytest.mark.parametrize("reference", ["catalog:missing", "feature:parking-controls"])
def test_catalog_conditions_need_resolved_typed_targets(bundle, reference):
    item = nodes_of(bundle, "CatalogItem")[0]
    item["properties"]["conditions"] = [
        {
            "kind": "requires_all",
            "catalog_item_ids": [reference],
            "description": "Synthetic condition.",
        }
    ]
    assert_invalid(bundle, "invalid condition CatalogItem reference")


def test_catalog_condition_cannot_require_itself(bundle):
    item = nodes_of(bundle, "CatalogItem")[0]
    item["properties"]["conditions"] = [
        {
            "kind": "requires_all",
            "catalog_item_ids": [item["id"]],
            "description": "Synthetic condition.",
        }
    ]
    assert_invalid(bundle, "cannot reference itself")


def test_package_membership_is_acyclic_and_stays_in_one_edition(bundle):
    edge = next(edge for edge in bundle["edges"] if edge["type"] == "INCLUDES")
    member = node(bundle, edge["target_id"])
    member["properties"]["item_kind"] = "package"
    add_edge(bundle, "INCLUDES", member["id"], edge["source_id"], "Synthetic scope transfer.")
    assert_invalid(bundle, "cyclic package membership")


def test_only_a_package_can_have_members(bundle):
    edge = next(edge for edge in bundle["edges"] if edge["type"] == "INCLUDES")
    node(bundle, edge["source_id"])["properties"]["item_kind"] = "equipment"
    assert_invalid(bundle, "only a package can include catalog items")


@pytest.mark.parametrize("relation", ["INCLUDES", "condition"])
def test_catalog_references_cannot_mix_original_editions(bundle, relation):
    edge = next(edge for edge in bundle["edges"] if edge["type"] == "INCLUDES")
    item, member = node(bundle, edge["source_id"]), node(bundle, edge["target_id"])
    evidence_edge = next(
        link
        for link in bundle["edges"]
        if link["type"] == "DERIVED_FROM" and link["source_id"] == member["id"]
    )
    evidence = copy.deepcopy(node(bundle, evidence_edge["target_id"]))
    evidence.update(id="evidence:test-new-edition", entity_key="evidence:test-new-edition")
    evidence["properties"].update(record_key="test-new-edition", dedup_key="test-new-edition")
    source_edge = next(
        link
        for link in bundle["edges"]
        if link["type"] == "IN_SOURCE" and link["source_id"] == evidence_edge["target_id"]
    )
    source = copy.deepcopy(node(bundle, source_edge["target_id"]))
    source.update(id="source:test-new-edition", entity_key="source:test-new-edition")
    bundle["nodes"].extend([source, evidence])
    add_edge(bundle, "IN_SOURCE", evidence["id"], source["id"])
    evidence_edge["target_id"] = evidence["id"]
    if relation == "condition":
        item["properties"]["conditions"] = [
            {
                "kind": "requires_any",
                "catalog_item_ids": [member["id"]],
                "description": "Synthetic condition.",
            }
        ]
        message = "catalog condition crosses source editions"
    else:
        message = "package membership crosses source editions"
    assert_invalid(bundle, message)


def test_catalog_item_needs_original_evidence(bundle):
    item = nodes_of(bundle, "CatalogItem")[0]
    bundle["edges"] = [
        edge
        for edge in bundle["edges"]
        if not (edge["type"] == "DERIVED_FROM" and edge["source_id"] == item["id"])
    ]
    assert_invalid(bundle, "missing or cyclic evidence chain")
    assert_invalid(bundle, "exactly one original source edition")


def test_catalog_item_can_derive_from_multiple_excerpts_in_one_edition(bundle):
    item = nodes_of(bundle, "CatalogItem")[0]
    derived = next(
        edge
        for edge in bundle["edges"]
        if edge["type"] == "DERIVED_FROM" and edge["source_id"] == item["id"]
    )
    original_id = derived["target_id"]
    evidence = copy.deepcopy(node(bundle, original_id))
    evidence.update(id="evidence:test-another-page", entity_key="evidence:test-another-page")
    evidence["properties"].update(record_key="test-another-page", dedup_key="test-another-page")
    evidence["properties"]["locator"]["page"] += 1
    source = next(
        edge["target_id"]
        for edge in bundle["edges"]
        if edge["type"] == "IN_SOURCE" and edge["source_id"] == original_id
    )
    bundle["nodes"].append(evidence)
    add_edge(bundle, "IN_SOURCE", evidence["id"], source)
    add_edge(bundle, "DERIVED_FROM", item["id"], evidence["id"])
    assert validate_bundle(bundle) == []


@pytest.mark.parametrize("source_kind", ["feedback_dataset", "editorial_review"])
def test_catalog_identity_cannot_be_backed_by_feedback_or_editorial_interpretation(
    bundle, source_kind
):
    item = nodes_of(bundle, "CatalogItem")[0]
    evidence_id = next(
        edge["target_id"]
        for edge in bundle["edges"]
        if edge["type"] == "DERIVED_FROM" and edge["source_id"] == item["id"]
    )
    source_id = next(
        edge["target_id"]
        for edge in bundle["edges"]
        if edge["type"] == "IN_SOURCE" and edge["source_id"] == evidence_id
    )
    node(bundle, source_id)["properties"]["source_kind"] = source_kind
    assert_invalid(bundle, "CatalogItem needs an original product catalog source")


@pytest.mark.parametrize("kind", ["study_finding", "commercial_indicator"])
def test_statistical_signal_uses_the_correct_source_kind(bundle, kind):
    signal = next(
        item for item in nodes_of(bundle, "Signal") if item["properties"]["signal_kind"] == kind
    )
    edge = next(
        edge
        for edge in bundle["edges"]
        if edge["type"] == "DERIVED_FROM" and edge["source_id"] == signal["id"]
    )
    edge["target_id"] = "evidence:fixture-customer"
    edge["context_transfer"] = "Synthetic transfer to an unrelated feedback source."
    assert_invalid(bundle, "source kind does not match signal kind")


def test_acceptance_test_needs_conditions_when_method_is_defined(bundle):
    requirement, _ = baseline(bundle)
    criterion = requirement["properties"]["acceptance_criteria"][0]
    criterion.update(verification_method="benchmark_test", test_conditions=[])
    assert_invalid(bundle, "verified criterion needs explicit test conditions")


def test_launch_year_matches_the_successor_horizon(bundle):
    requirement, _ = baseline(bundle)
    requirement["properties"]["target_launch_year"] = int(bundle["as_of"][:4]) + 20
    assert_invalid(
        bundle, "target launch year must match requirement creation year plus horizon_years"
    )


def test_advancing_snapshot_preserves_historical_requirement_horizons(bundle):
    requirement, _ = baseline(bundle)
    requirement["properties"].update(horizon_years=4, target_launch_year=2030)
    requirement["properties"]["provenance"]["created_at"] = "2026-10-10T12:00:00Z"
    bundle["as_of"] = "2027-01-01"
    assert validate_bundle(bundle) == []


def test_new_requirement_revision_has_its_own_creation_horizon(bundle):
    requirement, _ = baseline(bundle)
    requirement["properties"].update(horizon_years=4, target_launch_year=2030)
    requirement["properties"]["provenance"]["created_at"] = "2026-10-10T12:00:00Z"
    bundle["as_of"] = "2027-01-01"
    revised = copy.deepcopy(requirement)
    revised.update(id="requirement:test-2027-revision", revision=2)
    revised["properties"]["provenance"]["created_at"] = "2027-01-01T12:00:00Z"
    bundle["nodes"].append(revised)
    for edge in list(bundle["edges"]):
        if edge["source_id"] == requirement["id"]:
            add_edge(
                bundle, edge["type"], revised["id"], edge["target_id"], edge["context_transfer"]
            )
    add_edge(bundle, "SUPERSEDES", revised["id"], requirement["id"])
    assert_invalid(
        bundle, "target launch year must match requirement creation year plus horizon_years"
    )
    revised["properties"]["target_launch_year"] = 2031
    assert validate_bundle(bundle) == []


@pytest.mark.parametrize("field", ["created_at", "retrieved_at", "decided_at"])
def test_observed_events_cannot_come_from_after_the_snapshot(bundle, field):
    if field == "created_at":
        subject = node(bundle, "signal:fixture-customer")
        subject["properties"]["provenance"][field] = "2199-01-01T12:00:00Z"
    elif field == "retrieved_at":
        subject = nodes_of(bundle, "SourceDocument")[0]
        subject["properties"][field] = "2199-01-01T12:00:00Z"
    else:
        subject = nodes_of(bundle, "Decision")[0]
        subject["properties"][field] = "2199-01-01T12:00:00Z"
    assert_invalid(bundle, f"{field} event date is after bundle as_of")


def test_requirement_revision_needs_exact_previous_revision(bundle):
    requirement, _ = baseline(bundle)
    previous = copy.deepcopy(requirement)
    previous.update(id="requirement:test-previous", revision=1)
    requirement["revision"] = 3
    bundle["nodes"].append(previous)
    add_edge(bundle, "SUPERSEDES", requirement["id"], previous["id"])
    assert_invalid(bundle, "consecutive previous revision")


def test_malformed_typed_endpoints_report_errors_without_crashing(bundle):
    requirement, _ = baseline(bundle)
    add_edge(bundle, "BASELINED_ON", requirement["id"], "source:fixture-feedback")
    add_edge(bundle, "IS_VARIANT_OF", "source:fixture-feedback", "feature:parking-controls")
    add_edge(bundle, "INCLUDES", "feature:parking-controls", "source:fixture-feedback")
    assert_invalid(bundle, "invalid Requirement -> SourceDocument relationship")
