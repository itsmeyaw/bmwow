"""Consumer example for the synthetic parking requirement, not a new ontology API.

The JSON option emits the existing RequirementDossier wire payload unchanged.
Text output groups stored edges by product question without duplicating objects
or discarding the rationale attached to each occurrence. No raw data is read.
"""

import argparse
import json
from pathlib import Path

from bmwow.ontology import GraphBundle, RequirementDossier, get_requirement_context
from bmwow.ontology.models import Edge

FIXTURE = Path(__file__).resolve().parents[1] / "contracts/ontology/examples/synthetic.json"
REQUIREMENT = "requirement:fixture-parking"


def question_edges(dossier: RequirementDossier) -> dict[str, list[Edge]]:
    """A presentation recipe over existing edges; never treat a partial trace as complete."""
    if dossier.truncated or dossier.trace.truncated:
        raise ValueError("Incomplete dossier: retrieve the missing context before summarizing.")
    requirement_id = dossier.requirement.id
    edges = dossier.trace.edges
    addresses = [
        edge for edge in edges if edge.type == "ADDRESSES" and edge.source_id == requirement_id
    ]
    need_ids = {edge.target_id for edge in addresses}
    return {
        "What already exists on the BMW?": [
            edge
            for edge in edges
            if edge.type == "BASELINED_ON" and edge.source_id == requirement_id
        ],
        "Why does the customer need exist?": addresses
        + [
            edge
            for edge in edges
            if edge.type in {"SUPPORTS", "CHALLENGES"} and edge.target_id in need_ids
        ],
        "Why was this proposal made?": [
            edge
            for edge in edges
            if (edge.type == "JUSTIFIED_BY" and edge.source_id == requirement_id)
            or (edge.type == "SUPPORTS" and edge.target_id == requirement_id)
        ],
        "What argues against or limits it?": [edge for edge in edges if edge.type == "CHALLENGES"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit the existing dossier contract.")
    args = parser.parse_args()
    bundle = GraphBundle.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    dossier = get_requirement_context(bundle, {"requirement_id": REQUIREMENT})
    if args.json:
        print(dossier.model_dump_json(indent=2))
        return

    sections = question_edges(dossier)
    nodes = {node.id: node for node in dossier.trace.nodes}
    requirement = dossier.requirement
    print(f"SYNTHETIC EXAMPLE | {requirement.id} | revision {requirement.revision}")
    print(requirement.properties.statement)
    print(
        f"Intent: {requirement.properties.change_intent}; "
        f"baseline: {requirement.properties.baseline_status}; review: {dossier.review.status}"
    )
    for question, edges in sections.items():
        print(f"\n{question}")
        for edge in edges:
            print(f"  {edge.source_id} --{edge.type}--> {edge.target_id}")
            print(f"    edge: {edge.id}")
            print(f"    rationale: {edge.rationale}")
            if edge.context_transfer:
                print(f"    scope transfer: {edge.context_transfer}")
            for node_id in (edge.source_id, edge.target_id):
                node = nodes[node_id]
                statement = getattr(node.properties, "statement", None)
                if statement:
                    print(f"    {node_id}: {statement}")
                if node.type == "Signal":
                    props = node.properties
                    availability = (
                        f"; availability={props.capability.availability}"
                        if props.capability
                        else ""
                    )
                    print(
                        f"    kind={props.signal_kind}; status={props.epistemic_status}{availability}"
                    )

    print("\nOriginals (one entry per Evidence ID; reasoning paths reuse these objects)")
    for node in dossier.trace.nodes:
        if node.type != "Evidence":
            continue
        source_edge = next(
            edge
            for edge in dossier.trace.edges
            if edge.type == "IN_SOURCE" and edge.source_id == node.id
        )
        print(f"  {node.id} --IN_SOURCE--> {source_edge.target_id}")
        print(f"    locator: {json.dumps(node.properties.locator.model_dump(mode='json'))}")
    print("\nAssumptions: " + ", ".join(dossier.assumption_ids))
    print("The acceptance threshold is a proposed target; no physical switch is mandated.")


if __name__ == "__main__":
    main()
