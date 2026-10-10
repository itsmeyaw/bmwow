"""Acceptance questions for frontend and orchestration over the existing dossier."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from bmwow.ontology import RequirementDossier, get_requirement_context

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts/ontology/examples/synthetic.json"
EXAMPLE = ROOT / "scripts/inspect_parking_dossier.py"
REQUIREMENT = "requirement:fixture-parking"
NEED = "need:fixture-usability"
CUSTOMER = "signal:fixture-customer"
QUESTION_EDGES = runpy.run_path(str(EXAMPLE))["question_edges"]


@pytest.fixture
def bundle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def matching(edges, relation, *, source=None, target=None):
    return [
        edge
        for edge in edges
        if edge.type == relation
        and (source is None or edge.source_id == source)
        and (target is None or edge.target_id == target)
    ]


def test_existing_bmw_offering_has_a_qualified_claim_and_original_catalog_path(bundle):
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
    baseline, _, _, _ = QUESTION_EDGES(dossier).values()
    assert len(baseline) == 1
    nodes = {node.id: node for node in dossier.trace.nodes}
    claim = nodes[baseline[0].target_id]
    assert claim.id == "signal:fixture-baseline-parking"
    assert claim.properties.signal_kind == "product_capability"
    assert claim.properties.capability.availability == "standard"
    assert claim.properties.capability.measurement is None
    assert claim.properties.epistemic_status == "publisher_claim"
    assert claim.properties.context.vehicle_model_ids == ["vehicle:bmw-g60"]
    assert claim.properties.context.market_ids == ["market:US"]
    original = matching(dossier.trace.edges, "DERIVED_FROM", source=claim.id)[0].target_id
    item = matching(dossier.trace.edges, "DESCRIBES", source=claim.id)[0].target_id
    assert original == "evidence:fixture-catalog-parking"
    assert nodes[original].properties.locator.page == 1
    assert "standard equipment" in nodes[original].properties.raw_text
    source = matching(dossier.trace.edges, "IN_SOURCE", source=original)[0].target_id
    item_original = matching(dossier.trace.edges, "DERIVED_FROM", source=item)[0].target_id
    assert matching(dossier.trace.edges, "IN_SOURCE", source=item_original)[0].target_id == source
    assert source == "source:fixture-catalog"


def test_need_support_and_selected_proposal_reasons_remain_distinct_occurrences(bundle):
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
    _, needs, reasons, challenges = QUESTION_EDGES(dossier).values()
    assert {edge.target_id for edge in matching(needs, "ADDRESSES")} == {NEED}
    assert {edge.source_id for edge in matching(needs, "SUPPORTS")} == {
        CUSTOMER,
        "signal:fixture-public-positive",
        "signal:fixture-competitor",
        "trend:fixture-controls",
        "signal:fixture-study-mean",
        "signal:fixture-study-share",
    }
    assert {edge.target_id for edge in matching(reasons, "JUSTIFIED_BY")} == {
        CUSTOMER,
        "signal:fixture-competitor",
        "trend:fixture-controls",
    }
    support = matching(needs, "SUPPORTS", source=CUSTOMER)[0]
    selected = matching(reasons, "JUSTIFIED_BY", target=CUSTOMER)[0]
    assert support.target_id == NEED and selected.source_id == REQUIREMENT
    assert support.id != selected.id and support.rationale != selected.rationale
    assert sum(node.id == CUSTOMER for node in dossier.trace.nodes) == 1
    assert sum(node.id == "evidence:fixture-customer" for node in dossier.trace.nodes) == 1
    originals = {edge["id"]: edge for edge in bundle["edges"]}
    for edge in [support, selected, *challenges]:
        assert edge.model_dump(mode="json") == originals[edge.id]


def test_challenge_and_uncertainty_are_not_demand_or_approval(bundle):
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
    _, _, _, challenges = QUESTION_EDGES(dossier).values()
    assert [(edge.source_id, edge.target_id) for edge in challenges] == [
        ("signal:fixture-public-challenge", REQUIREMENT)
    ]
    nodes = {node.id: node for node in dossier.trace.nodes}
    assert nodes["signal:fixture-competitor"].properties.capability.availability == "announced"
    assert "signal:fixture-sales" not in nodes and "evidence:fixture-sales" not in nodes
    mean = nodes["evidence:fixture-study-mean"].properties.measurement
    share = nodes["evidence:fixture-study-share"].properties.measurement
    assert mean.scale is None and mean.sample_size is None
    assert share.sample_size is None and share.denominator is None
    assert "assumption:fixture-persistence" in dossier.assumption_ids
    assert dossier.requirement.properties.acceptance_criteria[0].basis == "proposed_target"
    assert dossier.review.status == "unreviewed" and dossier.review.priority is None
    assert dossier.decisions[0].properties.action == "comment"
    assert len([node for node in dossier.trace.nodes if node.type == "Evidence"]) == 8


@pytest.mark.parametrize("target", [NEED, "assumption:fixture-persistence"])
def test_opposition_identifies_the_challenged_need_or_premise(bundle, target):
    challenge = next(edge for edge in bundle["edges"] if edge["type"] == "CHALLENGES")
    challenge["target_id"] = target
    challenge["rationale"] = "Synthetic limiting evidence for this specific target."
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
    _, needs, _, challenges = QUESTION_EDGES(dossier).values()
    assert len(challenges) == 1 and challenges[0].target_id == target
    assert bool(matching(needs, "CHALLENGES")) == (target == NEED)
    assert "evidence:fixture-public-challenge" in {node.id for node in dossier.trace.nodes}


def test_direct_requirement_support_does_not_replace_selected_justification(bundle):
    bundle["edges"].append(
        {
            "id": "edge:consumer-direct-support",
            "type": "SUPPORTS",
            "source_id": CUSTOMER,
            "target_id": REQUIREMENT,
            "rationale": "The same experience separately corroborates the proposal's outcome.",
            "context_transfer": None,
        }
    )
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
    _, needs, reasons, _ = QUESTION_EDGES(dossier).values()
    assert len(matching(needs, "SUPPORTS", source=CUSTOMER)) == 1
    assert len(matching(reasons, "JUSTIFIED_BY", target=CUSTOMER)) == 1
    assert len(matching(reasons, "SUPPORTS", source=CUSTOMER, target=REQUIREMENT)) == 1
    assert sum(node.id == CUSTOMER for node in dossier.trace.nodes) == 1


@pytest.mark.parametrize("flag", ["dossier", "trace"])
def test_consumer_example_does_not_summarize_an_incomplete_dossier(bundle, flag):
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
    if flag == "dossier":
        dossier.truncated = True
    else:
        dossier.trace.truncated = True
    with pytest.raises(ValueError, match="Incomplete dossier"):
        QUESTION_EDGES(dossier)


def test_example_json_uses_existing_dossier_wire_contract(bundle):
    result = subprocess.run(
        [sys.executable, str(EXAMPLE), "--json"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    parsed = RequirementDossier.model_validate_json(result.stdout)
    assert parsed == get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
