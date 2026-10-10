"""Propose exact theme mappings privately; no proposal becomes a reviewed association."""

import argparse
import csv
import json
import re
from pathlib import Path

from bmwow.knowledge.config import VfcMapping
from bmwow.knowledge.manifest import load_manifest
from bmwow.ontology.models import Feature


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--feedback-dir", type=Path, required=True)
    parser.add_argument("--import-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = load_manifest(args.config)
    for node_id, label, key, definition in (
        (
            "feature:seat-comfort",
            "Seat comfort",
            "seat_comfort",
            "Perceived comfort, support, and ergonomic fit of vehicle seating. This concept does not establish a specific equipment offering.",
        ),
        (
            "feature:seat-ventilation",
            "Seat ventilation",
            "seat_ventilation",
            "Air circulation through a seat intended to affect occupant thermal comfort; distinct from heating, massage, and cabin climate control.",
        ),
    ):
        if node_id not in {node.id for node in manifest.context_nodes}:
            manifest.context_nodes.append(
                Feature(
                    id=node_id,
                    entity_key=node_id,
                    label=label,
                    revision=1,
                    type="Feature",
                    properties=dict(definition=definition, domains=["interior"], aliases=[]),
                )
            )
            manifest.knowledge.feature_keys[node_id] = key
            manifest.pending_decisions.append(f"Review proposed canonical definition: {node_id}")
    expression = re.compile(r"seat|sitz|comfort|komfort", re.IGNORECASE)
    ventilation = re.compile(r"ventilat|cooling|belüft|belueft", re.IGNORECASE)
    labels = set()
    for path in sorted(args.feedback_dir.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            labels.update(
                row["Vfc level2 Name"].replace("\u00a0", " ").strip()
                for row in csv.DictReader(handle)
                if row.get("Vfc level2 Name") and expression.search(row["Vfc level2 Name"])
            )
    questions = json.loads(args.import_report.read_text(encoding="utf-8"))["questions"]
    proposed = 0
    for originals, mappings in (
        (labels, manifest.knowledge.vfc_mappings),
        (questions, manifest.knowledge.study_mappings),
    ):
        for original in sorted(originals):
            if not expression.search(original) or original in mappings:
                continue
            mappings[original] = VfcMapping(
                feature_id="feature:seat-ventilation"
                if ventilation.search(original)
                else "feature:seat-comfort",
                status="proposed",
                rationale="Lexical suggestion only; verify meaning, body position, and specificity against the original source.",
            )
            proposed += 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(manifest.model_dump_json(indent=2) + "\n")
    print(json.dumps({"mapping_proposals": proposed, "reviewed_automatically": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
