"""Stage competitors and their web-extracted values as a closed graph bundle for the knowledge layer.

    uv run python -m scripts.stage_competitors --curation ../data/knowledge/curation.json \\
        --analysis ../data/processed/analyses/<run_id>.json \\
        --output ../data/knowledge/competitors.staging.json [--list]

1. Competitors (bmwow/knowledge/competitors.yaml): VehicleModel nodes and COMPETES_WITH edges go
   into the staging bundle; their model profiles (segment, powertrain, sold regions) are written
   into the curation file, which keeps a curated copy of the nodes as context.
2. Values (optional, from a saved analysis): every competition finding with a number and a web
   source becomes Evidence (web_excerpt: the verbatim quote that contains the number) -> Signal
   (competitor_capability with measurement, variant and engine type) -> CONCERNS Feature. They are
   machine extractions, not human-reviewed; the provenance and limitations say so.

Import with `scripts.import_knowledge ... --catalog-bundle <catalog> --catalog-bundle <this>`. Once
stored, the competition agent reads these values from the knowledge layer instead of extracting
them again, so runs become reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bmwow.agent.models.evidence import Finding, SituationAnalysis, Source
from bmwow.agent.rules import powertrain_of
from bmwow.agent.structure import normalize_quantity
from bmwow.ontology import GraphBundle, validate_bundle

COMPETITORS = Path(__file__).resolve().parents[1] / "bmwow" / "knowledge" / "competitors.yaml"
NOTE = "PROPOSED competitor selection (public information); team review pending."


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{hashlib.sha1('|'.join(parts).encode()).hexdigest()[:16]}"


def competitor_nodes(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": e["id"],
            "entity_key": e["id"],
            "type": "VehicleModel",
            "label": e["label"],
            "revision": 1,
            "properties": {
                "brand": e["brand"],
                "vehicle_line": e["vehicle_line"],
                "generation_code": e.get("generation_code"),
                "model_year": None,
                "variant": None,
                "aliases": e.get("aliases", []),
            },
        }
        for e in entries
    ]


def competes_edges(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"edge:competes_with:{e['id']}:{target}",
            "type": "COMPETES_WITH",
            "source_id": e["id"],
            "target_id": target,
            "rationale": e["rationale"],
            "context_transfer": f"Segment {e['segment']}; regions {', '.join(e['sold_regions'])}.",
        }
        for e in entries
        for target in e["competes_with"]
    ]


def _who(subject: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    s = subject.casefold()
    for e in entries:
        if s in {n.casefold() for n in [e["label"], *e.get("aliases", [])]}:
            return e
    return None


def _quote(finding: Finding, source: Source) -> str | None:
    """The verified quote (one of the ' … '-joined excerpt parts) that states the number."""
    from bmwow.agent.validation import number_in_text

    q = finding.quantity
    assert q is not None
    for part in source.excerpt.split(" … "):
        if number_in_text(q.value, part, q.unit):
            return part.strip()
    return None


def value_nodes(
    analysis: SituationAnalysis, entries: list[dict[str, Any]], feature_ids: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    report = analysis.reports.get("competition")
    if report is None:
        return [], [], []
    sources = {s.id: s for s in report.sources}
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    listing: list[str] = []
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for f in report.findings:
        q, who = f.quantity, _who(f.subject, entries)
        web = [sources[s] for s in f.source_ids if s.startswith("web:") and s in sources]
        if q is None or who is None or not web or f.attribute not in feature_ids:
            continue
        src = web[0]
        quote = _quote(f, src)
        if quote is None:
            continue
        parts = [x.strip() for x in q.qualifier.split(";") if x.strip()]
        variant = next((x[8:] for x in parts if x.lower().startswith("variant ")), None)
        pt = next((x.split()[1] for x in parts if x.lower().startswith("powertrain ")), None)
        pt = pt or powertrain_of(variant) or powertrain_of(f.subject) or "unknown"
        standard = "; ".join(
            x
            for x in parts
            if not x.lower().startswith(("variant ", "powertrain ")) and x != f.region
        )
        value, unit = normalize_quantity(q.value, q.unit)
        doc = _id("source:web", src.ref)
        ev = _id("evidence:web", src.ref, quote, who["id"], pt)  # one scope per evidence
        sig = _id("signal:competitor", src.ref, quote, f.attribute, variant or "", str(value))
        context = {
            "vehicle_model_ids": [who["id"]],
            "market_ids": [],
            "country_codes": [],
            "engine_types": [pt],
            "as_of": src.retrieved_at.date().isoformat(),
            "scope_notes": [f"Region: {f.region}"] if f.region else [],
        }
        nodes[doc] = {
            "id": doc,
            "entity_key": doc,
            "type": "SourceDocument",
            "label": (src.title or src.ref)[:200],
            "revision": 1,
            "properties": {
                "source_kind": "editorial_review",
                "origin": "external",
                "location": {"kind": "web", "url": src.ref},
                "publisher": re.sub(r"^https?://(www\.)?", "", src.ref).split("/")[0],
                "publication_date": None,
                "retrieved_at": src.retrieved_at.isoformat().replace("+00:00", "Z"),
                "content_hash": None,
                "source_role": "secondary",
                "independence_group": None,
                "access": "public",
                "quality_notes": ["Saved web page (approved URL list); text extracted from HTML."],
            },
        }
        nodes[ev] = {
            "id": ev,
            "entity_key": ev,
            "type": "Evidence",
            "label": quote[:120],
            "revision": 1,
            "properties": {
                "evidence_kind": "web_excerpt",
                "record_key": ev,
                "dedup_key": ev,
                "source_channel": "web_corpus",
                "locator": {"kind": "web", "selector": None, "text_fragment": quote[:500]},
                "raw_text": quote,
                "measurement": None,
                "raw_classifications": [],
                "context": context,
                "limitations": [
                    "Third-party web page; the value was not checked against the maker."
                ],
            },
        }
        measurement = {
            "metric": f.attribute,
            "value": value,
            "value_range": None,
            "unit": unit,
            "statistic": "scalar",
            "temporal_status": "unknown",
            "period": None,
            "sample_size": None,
            "denominator": None,
            "scale": None,
            "comparison_basis": "Value as stated on the cited page.",
            "population": None,
            "test_standard": standard or None,
            "conditions": [],
            "question": None,
            "response_category": None,
            "notes": [],
        }
        nodes[sig] = {
            "id": sig,
            "entity_key": sig,
            "type": "Signal",
            "label": f"{who['label']}: {f.attribute.replace('_', ' ')}",
            "revision": 1,
            "properties": {
                "signal_kind": "competitor_capability",
                "statement": f"{who['label']} {variant or ''}: {f.attribute.replace('_', ' ')} "
                f"{value:g} {unit}".replace("  ", " "),
                "epistemic_status": "publisher_claim",
                "sentiment": "not_applicable",
                "context": context,
                "public_context": None,
                "capability": {
                    "availability": "available_unspecified",
                    "variant": variant,
                    "measurement": measurement,
                    "notes": ["Machine extraction from a saved web page; not human-reviewed."],
                    "conditions": [],
                },
                "extraction_confidence": {
                    "level": "unassessed",
                    "reason": "LLM extraction; quote and number verified by code.",
                },
                "provenance": {
                    "actor_type": "software",
                    "actor_id": "bmwow-competition-agent",
                    "method": "llm_extraction",
                    "created_at": now,
                    "model": None,
                    "prompt_version": f"run:{analysis.run_id}",
                },
            },
        }
        for rel, target, why in (
            ("DERIVED_FROM", ev, "Interpretation of the quoted web excerpt."),
            ("CONCERNS", feature_ids[f.attribute], "The extracted value concerns this feature."),
        ):
            edges.append(
                {
                    "id": f"edge:{rel.lower()}:{sig}:{target}",
                    "type": rel,
                    "source_id": sig,
                    "target_id": target,
                    "rationale": why,
                    "context_transfer": None,
                }
            )
        edges.append(
            {
                "id": f"edge:in_source:{ev}",
                "type": "IN_SOURCE",
                "source_id": ev,
                "target_id": doc,
                "rationale": "Excerpt from this page.",
                "context_transfer": None,
            }
        )
        listing.append(
            f"{who['label']:24} {f.attribute:18} {value:>9g} {unit:10} {pt:5} {variant or '':28} "
            f"{standard[:20]:20} {src.ref[:60]}"
        )
    return list(nodes.values()), list({e["id"]: e for e in edges}.values()), listing


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--curation", type=Path, required=True)
    parser.add_argument(
        "--analysis", type=Path, action="append", default=[], help="saved run; repeat for several"
    )
    parser.add_argument("--competitors", type=Path, default=COMPETITORS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--list", action="store_true", help="print the staged values")
    args = parser.parse_args()

    entries = yaml.safe_load(args.competitors.read_text())
    curation = json.loads(args.curation.read_text())
    context = {n["id"]: n for n in curation["context_nodes"]}
    knowledge = curation["knowledge"]
    feature_ids = {key: fid for fid, key in knowledge["feature_keys"].items()}

    models = competitor_nodes(entries)
    for node in models:  # curated copies, so the profiles below refer to known models
        context[node["id"]] = node
    curation["context_nodes"] = list(context.values())
    for e in entries:
        knowledge["model_profiles"][e["id"]] = {
            "segment": e["segment"],
            "curation_note": NOTE,
            "powertrain": e.get("powertrain"),
            "sold_regions": e["sold_regions"],
        }
    args.curation.write_text(json.dumps(curation, indent=2, ensure_ascii=False) + "\n")

    nodes, edges, listing = [], [], []
    by_id: dict[str, dict[str, Any]] = {}
    edge_by_id: dict[str, dict[str, Any]] = {}
    for path in args.analysis:  # values of several runs, merged by id (same quote = same node)
        analysis = SituationAnalysis.model_validate_json(path.read_text())
        n, e, rows = value_nodes(analysis, entries, feature_ids)
        by_id.update({x["id"]: x for x in n if x["id"] not in by_id})
        edge_by_id.update({x["id"]: x for x in e})
        listing += rows
    nodes, edges = list(by_id.values()), list(edge_by_id.values())
    referenced = {e["target_id"] for e in edges} | {t for e in entries for t in e["competes_with"]}
    closure = [
        context[i]
        for i in sorted(referenced)
        if i in context and i not in {n["id"] for n in models}
    ]
    bundle = {
        "ontology_version": "0.2.0",
        "purpose": "production",
        "as_of": datetime.now(UTC).date().isoformat(),
        "description": "Competitor models and machine-extracted web values (proposed, not reviewed).",
        "nodes": [*models, *closure, *nodes],
        "edges": [*competes_edges(entries), *edges],
    }
    issues = validate_bundle(GraphBundle.model_validate_json(json.dumps(bundle)))
    if issues:
        raise SystemExit(f"staging bundle does not validate: {issues}")
    args.output.write_text(json.dumps(bundle, indent=1, ensure_ascii=False) + "\n")
    if args.list:
        print("\n".join(listing))
    print(
        f"{len(models)} competitors, {sum(n['type'] == 'Signal' for n in nodes)} values staged -> "
        f"{args.output}"
    )


if __name__ == "__main__":
    main()
