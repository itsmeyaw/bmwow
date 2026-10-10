"""Competency and mutation-boundary checks for deterministic agent tools."""

import copy
import json
from pathlib import Path

import pytest
from bmwow.ontology.tools import (
    OntologyQuery,
    RequirementProposal,
    build_agent_contracts,
    comparison_readiness,
    get_requirement_context,
    query_nodes,
    snapshot_fingerprint,
    trace_evidence,
    traverse,
    validate_proposal,
)
from bmwow.ontology.validation import validate_bundle
from jsonschema import Draft202012Validator
from pydantic import ValidationError

FIXTURE = Path(__file__).resolve().parents[2] / "contracts/ontology/examples/synthetic.json"
REQUIREMENT = "requirement:fixture-parking"


@pytest.fixture
def bundle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def node(bundle, node_id):
    return next(item for item in bundle["nodes"] if item["id"] == node_id)


def edge(bundle, relation, source, target, suffix):
    bundle["edges"].append(
        {
            "id": "edge:test-" + suffix,
            "type": relation,
            "source_id": source,
            "target_id": target,
            "rationale": "Synthetic integration test relationship.",
            "context_transfer": None,
        }
    )


def proposal(bundle, *, revision=2):
    requirement = copy.deepcopy(node(bundle, REQUIREMENT))
    requirement["id"] = f"requirement:fixture-parking:v{revision}"
    requirement["revision"] = revision
    requirement["properties"]["provenance"].update(
        {
            "actor_type": "software",
            "actor_id": "test-agent",
            "method": "llm_extraction",
            "model": "synthetic-model",
            "prompt_version": "synthetic-v1",
        }
    )
    links = []
    for original in bundle["edges"]:
        if original["source_id"] != REQUIREMENT:
            continue
        link = copy.deepcopy(original)
        link["id"] = "edge:proposal-" + original["id"].split(":", 1)[1]
        link["source_id"] = requirement["id"]
        links.append(link)
    links.append(
        {
            "id": "edge:proposal-supersedes",
            "type": "SUPERSEDES",
            "source_id": requirement["id"],
            "target_id": REQUIREMENT,
            "rationale": "Revised synthetic proposal.",
            "context_transfer": None,
        }
    )
    return {"requirement": requirement, "edges": links}


def decision(bundle, action, suffix, *, priority=None):
    review = copy.deepcopy(node(bundle, "decision:fixture-comment"))
    review["id"] = review["entity_key"] = "decision:test-" + suffix
    review["properties"].update({"action": action, "priority": priority})
    bundle["nodes"].append(review)
    edge(bundle, "REVIEWS", review["id"], REQUIREMENT, "review-" + suffix)


def test_scoped_query_does_not_infer_unknown_market_or_variant_scope(bundle):
    result = query_nodes(
        bundle,
        {
            "node_types": ["Signal"],
            "signal_kinds": ["customer_feedback"],
            "vehicle_model_ids": ["vehicle:bmw-g60"],
            "market_ids": ["market:US"],
        },
    )
    assert [item.id for item in result.nodes] == ["signal:fixture-customer"]
    unknown = query_nodes(bundle, {"node_types": ["Signal"], "market_ids": ["market:not-defined"]})
    assert unknown.total == 0
    variant = query_nodes(
        bundle,
        {
            "ids": ["signal:fixture-baseline-parking"],
            "vehicle_model_ids": ["vehicle:bmw-g60-fixture-ev"],
        },
    )
    assert variant.total == 0


def test_country_and_engine_query_preserves_observed_scope(bundle):
    result = query_nodes(
        bundle, {"node_types": ["Signal"], "country_codes": ["US"], "engine_types": ["bev"]}
    )
    assert {item.id for item in result.nodes} == {
        "signal:fixture-range",
        "signal:fixture-ac-standard",
        "signal:fixture-ac-optional",
    }
    assert not query_nodes(
        bundle, {"country_codes": ["DE"], "ids": ["signal:fixture-customer"]}
    ).nodes
    assert not query_nodes(bundle, {"engine_types": ["ice"]}).nodes


def test_query_exposes_bmw_baseline_and_future_sales_separately(bundle):
    baseline = query_nodes(
        bundle, {"signal_kinds": ["product_capability"], "feature_ids": ["feature:ac-charging"]}
    )
    assert {item.id for item in baseline.nodes} == {
        "signal:fixture-ac-standard",
        "signal:fixture-ac-optional",
    }
    assert sorted(item.properties.capability.measurement.value for item in baseline.nodes) == [
        9.0,
        18.0,
    ]
    projected = query_nodes(bundle, {"signal_kinds": ["commercial_indicator"]})
    assert [item.id for item in projected.nodes] == ["signal:fixture-sales"]
    future_signal = query_nodes(
        bundle,
        {"signal_kinds": ["commercial_indicator"], "temporal_status": "source_reported_future"},
    )
    assert [item.id for item in future_signal.nodes] == ["signal:fixture-sales"]
    evidence = query_nodes(
        bundle, {"node_types": ["Evidence"], "temporal_status": "source_reported_future"}
    )
    assert "evidence:fixture-sales" in {item.id for item in evidence.nodes}


def test_quantitative_signal_temporal_filter_requires_all_direct_inputs_to_agree(bundle):
    original = node(bundle, "evidence:fixture-sales")
    historical = copy.deepcopy(original)
    historical["id"] = historical["entity_key"] = "evidence:test-historical-sales"
    historical["properties"]["record_key"] = historical["properties"]["dedup_key"] = historical[
        "id"
    ]
    historical["properties"]["measurement"].update(
        {"temporal_status": "historical", "period": {"label": "2025", "start": None, "end": None}}
    )
    bundle["nodes"].append(historical)
    edge(bundle, "IN_SOURCE", historical["id"], "source:fixture-sales", "historical-sales-source")
    edge(bundle, "DERIVED_FROM", "signal:fixture-sales", historical["id"], "mixed-sales-input")
    assert validate_bundle(bundle) == []
    assert not query_nodes(
        bundle,
        {"signal_kinds": ["commercial_indicator"], "temporal_status": "source_reported_future"},
    ).nodes
    assert not query_nodes(
        bundle, {"signal_kinds": ["commercial_indicator"], "temporal_status": "historical"}
    ).nodes
    unknown = query_nodes(
        bundle, {"signal_kinds": ["commercial_indicator"], "temporal_status": "unknown"}
    )
    assert [item.id for item in unknown.nodes] == ["signal:fixture-sales"]


def test_query_pagination_is_deterministic_and_bounded(bundle):
    result = query_nodes(bundle, {"limit": 2})
    again = query_nodes({**bundle, "nodes": list(reversed(bundle["nodes"]))}, {"limit": 2})
    assert [item.id for item in result.nodes] == [item.id for item in again.nodes]
    assert result.total > 2 and result.truncated
    with pytest.raises(ValidationError):
        OntologyQuery(limit=101)


def test_bidirectional_traversal_preserves_original_edge_direction(bundle):
    incoming = traverse(
        bundle,
        {
            "node_id": "source:fixture-feedback",
            "relationship_types": ["IN_SOURCE"],
            "direction": "incoming",
        },
    )
    assert len(incoming.edges) == 1
    assert incoming.edges[0].source_id == "evidence:fixture-customer"
    assert incoming.edges[0].target_id == "source:fixture-feedback"
    outgoing = traverse(
        bundle,
        {
            "node_id": "source:fixture-feedback",
            "relationship_types": ["IN_SOURCE"],
            "direction": "outgoing",
        },
    )
    assert not outgoing.edges


def test_trace_contains_baseline_original_locators_and_nested_challenges(bundle):
    bundle["edges"] = [
        link
        for link in bundle["edges"]
        if not (link["type"] == "CHALLENGES" and link["target_id"] == REQUIREMENT)
    ]
    edge(
        bundle,
        "CHALLENGES",
        "signal:fixture-public-challenge",
        "need:fixture-usability",
        "need-challenge",
    )
    edge(
        bundle,
        "CHALLENGES",
        "signal:fixture-public-challenge",
        "assumption:fixture-persistence",
        "assumption-challenge",
    )
    result = trace_evidence(bundle, {"node_id": REQUIREMENT})
    nodes = {item.id: item for item in result.nodes}
    assert {
        "evidence:fixture-customer",
        "evidence:fixture-public-challenge",
        "source:fixture-public",
        "signal:fixture-baseline-parking",
        "catalog:fixture-parking",
    }.issubset(nodes)
    assert nodes["evidence:fixture-public-challenge"].properties.locator.kind == "web"
    assert nodes["evidence:fixture-catalog-parking"].properties.locator.page > 0
    assert {link.target_id for link in result.edges if link.type == "CHALLENGES"} == {
        "need:fixture-usability",
        "assumption:fixture-persistence",
    }
    assert not result.truncated


def test_trace_reports_when_result_is_incomplete(bundle):
    result = trace_evidence(bundle, {"node_id": REQUIREMENT, "max_nodes": 2})
    assert len(result.nodes) == 2 and result.truncated
    shallow = trace_evidence(bundle, {"node_id": REQUIREMENT, "max_depth": 1})
    assert shallow.truncated


def test_trace_follows_criterion_evidence_without_fabricating_an_edge(bundle):
    node(bundle, REQUIREMENT)["properties"]["acceptance_criteria"][0]["supporting_evidence_ids"] = [
        "evidence:fixture-sales"
    ]
    result = trace_evidence(bundle, {"node_id": REQUIREMENT})
    assert {"evidence:fixture-sales", "source:fixture-sales"}.issubset(
        {item.id for item in result.nodes}
    )
    reference = next(
        item
        for item in result.references
        if item.source_id == REQUIREMENT and item.target_id == "evidence:fixture-sales"
    )
    assert "supporting_evidence_ids" in reference.field
    assert not any(
        link.source_id == REQUIREMENT and link.target_id == "evidence:fixture-sales"
        for link in result.edges
    )


def test_trace_recursively_follows_package_prerequisite_references(bundle):
    result = trace_evidence(bundle, {"node_id": "catalog:fixture-advanced"})
    expected = {
        "catalog:fixture-comfort",
        "catalog:fixture-charging",
        "catalog:fixture-trim-smooth",
        "catalog:fixture-trim-soft",
        "catalog:fixture-retrofit",
        "evidence:fixture-catalog-comfort",
        "evidence:fixture-catalog-charging",
    }
    assert expected.issubset({item.id for item in result.nodes})
    assert any(
        item.source_id == "catalog:fixture-advanced"
        and item.target_id == "catalog:fixture-comfort"
        and "catalog_item_ids" in item.field
        for item in result.references
    )
    assert not any(
        link.source_id == "catalog:fixture-advanced" and link.target_id == "catalog:fixture-comfort"
        for link in result.edges
    )
    assert not result.truncated


def test_dossier_keeps_human_review_separate_from_comments_and_priority(bundle):
    decision(bundle, "approve", "approve")
    decision(bundle, "set_priority", "priority", priority=3)
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
    assert dossier.review.status == "approved"
    assert dossier.review.priority == 3
    assert dossier.review.decision_ids == ["decision:test-approve"]
    assert dossier.baseline_ids == ["signal:fixture-baseline-parking"]
    assert "assumption:fixture-persistence" in dossier.assumption_ids
    assert len(dossier.decisions) == 3


def test_conflicting_equal_time_reviews_are_ambiguous(bundle):
    decision(bundle, "approve", "approve")
    decision(bundle, "reject", "reject")
    review = get_requirement_context(bundle, {"requirement_id": REQUIREMENT}).review
    assert review.status == "ambiguous"
    assert set(review.decision_ids) == {"decision:test-approve", "decision:test-reject"}


def test_review_id_summaries_are_bounded_without_losing_conflicting_status(bundle):
    decision(bundle, "approve", "approve-first")
    decision(bundle, "approve", "approve-second")
    decision(bundle, "reject", "reject")
    decision(bundle, "set_priority", "priority-first", priority=3)
    decision(bundle, "set_priority", "priority-second", priority=3)
    decision(bundle, "set_priority", "priority-third", priority=3)
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT, "max_nodes": 2})
    assert dossier.review.status == "ambiguous"
    assert dossier.review.priority == 3
    assert len(dossier.review.decision_ids) == len(dossier.review.priority_decision_ids) == 2
    assert len(dossier.decisions) == 2 and dossier.truncated


def test_new_revision_has_no_inherited_review_and_is_latest_query_default(bundle):
    decision(bundle, "approve", "approve")
    result = validate_proposal(bundle, proposal(bundle), actor_id="test-agent")
    assert result.accepted and result.candidate is not None
    new_id = "requirement:fixture-parking:v2"
    dossier = get_requirement_context(result.candidate, {"requirement_id": new_id})
    assert dossier.review.status == "unreviewed" and not dossier.decisions
    latest = query_nodes(result.candidate, {"node_types": ["Requirement"]})
    assert [item.id for item in latest.nodes] == [new_id]
    history = query_nodes(result.candidate, {"node_types": ["Requirement"], "latest_only": False})
    assert len(history.nodes) == 2


@pytest.mark.parametrize("relation", ["SUPPORTS", "CHALLENGES"])
@pytest.mark.parametrize("direction", ["incoming", "outgoing"])
def test_proposal_support_and_challenge_links_must_be_incoming(bundle, relation, direction):
    before = copy.deepcopy(bundle)
    candidate = proposal(bundle)
    new_id = candidate["requirement"]["id"]
    signal_id = "signal:fixture-public-challenge"
    candidate["edges"].append(
        {
            "id": "edge:proposal-incoming-argument",
            "type": relation,
            "source_id": signal_id if direction == "incoming" else new_id,
            "target_id": new_id if direction == "incoming" else signal_id,
            "rationale": "Synthetic argument assessed for this exact new revision.",
            "context_transfer": None,
        }
    )
    result = validate_proposal(bundle, candidate, actor_id="test-agent")
    assert result.accepted == (direction == "incoming")
    if direction == "incoming":
        assert validate_bundle(result.candidate) == []
        dossier = get_requirement_context(result.candidate, {"requirement_id": new_id})
        assert any(
            link.type == relation and link.target_id == new_id for link in dossier.trace.edges
        )
    else:
        assert {error.code for error in result.errors} == {"disallowed_change"}
        assert result.candidate is None
    assert bundle == before


def test_reconsidered_challenge_can_follow_a_revision_but_human_review_cannot(bundle):
    decision(bundle, "approve", "approve")
    decision(bundle, "set_priority", "priority", priority=3)
    candidate = proposal(bundle)
    challenge = copy.deepcopy(
        next(link for link in bundle["edges"] if link["type"] == "CHALLENGES")
    )
    challenge["id"] = "edge:reconsidered-challenge"
    challenge["target_id"] = candidate["requirement"]["id"]
    candidate["edges"].append(challenge)
    result = validate_proposal(bundle, candidate, actor_id="test-agent")
    assert result.accepted
    previous = get_requirement_context(result.candidate, {"requirement_id": REQUIREMENT})
    revised = get_requirement_context(
        result.candidate, {"requirement_id": candidate["requirement"]["id"]}
    )
    assert previous.review.status == "approved" and previous.review.priority == 3
    assert revised.review.status == "unreviewed" and revised.review.priority is None
    assert not revised.decisions
    assert any(link.id == challenge["id"] for link in revised.trace.edges)


def test_proposal_cannot_invent_a_signal_through_justification(bundle):
    candidate = proposal(bundle)
    next(link for link in candidate["edges"] if link["type"] == "JUSTIFIED_BY")["target_id"] = (
        "signal:not-ingested"
    )
    result = validate_proposal(bundle, candidate)
    assert not result.accepted and result.candidate is None
    assert {error.code for error in result.errors} == {"disallowed_change"}


def test_comparison_rejects_unknown_survey_bases_and_incompatible_scales(bundle):
    result = comparison_readiness(
        bundle, {"node_ids": ["evidence:fixture-study-mean", "evidence:fixture-study-share"]}
    )
    assert result.status == "not_ready"
    assert any("scale bounds" in message for message in result.blockers)
    assert any("sample size" in message for message in result.blockers)
    assert any("denominator" in message for message in result.blockers)
    assert any("statistic" in message for message in result.blockers)


def test_comparison_does_not_convert_units_or_configuration_conditions(bundle):
    result = comparison_readiness(
        bundle, {"node_ids": ["signal:fixture-ac-standard", "signal:fixture-ac-optional"]}
    )
    assert result.status == "not_ready"
    assert any("conditions" in message for message in result.blockers)
    assert any("availability" in message for message in result.blockers)
    node(bundle, "evidence:fixture-ac-optional")["properties"]["measurement"]["unit"] = "W"
    result = comparison_readiness(
        bundle, {"node_ids": ["evidence:fixture-ac-standard", "evidence:fixture-ac-optional"]}
    )
    assert any("unit" in message for message in result.blockers)


def test_equivalent_defined_measurements_are_ready_for_human_review(bundle):
    original = node(bundle, "evidence:fixture-sales")
    original["properties"]["measurement"]["comparison_basis"] = (
        "Same synthetic grouped scenario and volume definition."
    )
    second = copy.deepcopy(original)
    second["id"] = second["entity_key"] = "evidence:test-second-sales"
    second["properties"]["record_key"] = second["properties"]["dedup_key"] = second["id"]
    second["properties"]["measurement"]["value"] = 15000.0
    bundle["nodes"].append(second)
    edge(bundle, "IN_SOURCE", second["id"], "source:fixture-sales", "second-sales-source")
    result = comparison_readiness(bundle, {"node_ids": [original["id"], second["id"]]})
    assert result.status == "ready_for_review" and not result.blockers
    assert result.cautions
    assert any("engine_types scope is unknown" in message for message in result.cautions)


def test_valid_proposal_produces_closed_candidate_without_mutation(bundle):
    before = copy.deepcopy(bundle)
    result = validate_proposal(
        bundle,
        proposal(bundle),
        expected_fingerprint=snapshot_fingerprint(bundle),
        actor_id="test-agent",
    )
    assert result.accepted and result.candidate is not None
    assert validate_bundle(result.candidate) == []
    assert bundle == before
    assert len(result.candidate.nodes) == len(bundle["nodes"]) + 1
    assert result.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    "case",
    [
        "replace_requirement",
        "replace_edge",
        "human_author",
        "human_target",
        "wrong_actor",
        "skip_revision",
        "missing_supersedes",
        "older_supersedes",
        "missing_target",
        "decision",
        "extra_evidence",
    ],
)
def test_proposal_rejects_unsafe_or_incomplete_changes_without_mutation(bundle, case):
    before = copy.deepcopy(bundle)
    candidate = proposal(bundle)
    if case == "replace_requirement":
        candidate["requirement"]["id"] = REQUIREMENT
    elif case == "replace_edge":
        candidate["edges"][0]["id"] = bundle["edges"][0]["id"]
    elif case == "human_author":
        candidate["requirement"]["properties"]["provenance"]["actor_type"] = "human"
    elif case == "human_target":
        candidate["requirement"]["properties"]["acceptance_criteria"][0]["basis"] = (
            "human_set_target"
        )
    elif case == "wrong_actor":
        candidate["requirement"]["properties"]["provenance"]["actor_id"] = "another-agent"
    elif case == "skip_revision":
        candidate["requirement"]["revision"] = 3
    elif case == "missing_supersedes":
        candidate["edges"] = [link for link in candidate["edges"] if link["type"] != "SUPERSEDES"]
    elif case == "older_supersedes":
        candidate["edges"][-1]["target_id"] = "signal:fixture-customer"
    elif case == "missing_target":
        candidate["edges"][0]["target_id"] = "need:missing"
    elif case == "decision":
        candidate["edges"][0]["type"] = "REVIEWS"
    else:
        candidate["evidence"] = node(bundle, "evidence:fixture-customer")
    result = validate_proposal(bundle, candidate, actor_id="test-agent")
    assert not result.accepted and result.errors and result.candidate is None
    assert bundle == before


def test_proposal_validates_base_and_complete_merged_graph(bundle):
    candidate = proposal(bundle)
    candidate["edges"] = [link for link in candidate["edges"] if link["type"] != "JUSTIFIED_BY"]
    result = validate_proposal(bundle, candidate)
    assert {error.code for error in result.errors} == {"invalid_graph"}
    bundle["edges"] = [
        link
        for link in bundle["edges"]
        if not (link["type"] == "IN_SOURCE" and link["source_id"] == "evidence:fixture-customer")
    ]
    result = validate_proposal(bundle, proposal(bundle))
    assert "invalid_base" in {error.code for error in result.errors}
    with pytest.raises(ValueError, match="Invalid closed"):
        query_nodes(bundle, {})


def test_service_snapshot_precondition_catches_parallel_stale_proposal(bundle):
    fingerprint = snapshot_fingerprint(bundle)
    reordered = {
        **bundle,
        "nodes": list(reversed(bundle["nodes"])),
        "edges": list(reversed(bundle["edges"])),
    }
    assert snapshot_fingerprint(reordered) == fingerprint
    node(bundle, "feature:parking-controls")["label"] = "Updated synthetic label"
    result = validate_proposal(bundle, proposal(bundle), expected_fingerprint=fingerprint)
    assert not result.accepted and result.candidate is None
    assert "stale_snapshot" in {error.code for error in result.errors}


def test_new_logical_requirement_can_start_at_one_but_cannot_invent_history(bundle):
    candidate = proposal(bundle, revision=1)
    candidate["requirement"]["entity_key"] = "requirement:new-customer-outcome"
    candidate["edges"] = [link for link in candidate["edges"] if link["type"] != "SUPERSEDES"]
    assert validate_proposal(bundle, candidate).accepted
    candidate["requirement"]["revision"] = 2
    assert not validate_proposal(bundle, candidate).accepted


def test_contract_export_is_narrow_valid_json_schema(bundle):
    contracts = build_agent_contracts()
    assert contracts["ontology_version"] == bundle["ontology_version"]
    for schema in [*contracts["inputs"].values(), *contracts["outputs"].values()]:
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    requirements = contracts["inputs"]["validate_proposal"]
    assert "GraphBundle" not in requirements.get("$defs", {})
    assert "Decision" not in requirements.get("$defs", {})
    assert "Evidence" not in requirements.get("$defs", {})
    parsed = RequirementProposal.model_validate_json(json.dumps(proposal(bundle)))
    assert parsed.requirement.revision == 2
