"""Validate a closed ontology bundle, including evidence and review invariants."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from pydantic import ValidationError

from .models import GraphBundle
from .relationships import RELATIONSHIPS


def _measurement_errors(measurement: dict, as_of: str) -> list[str]:
    """Apply identical quantitative rules to observations and capability claims."""
    errors = []
    value, interval = measurement["value"], measurement["value_range"]
    if (value is None) == (interval is None):
        return ["measurement needs exactly one scalar value or value_range"]
    values = [value] if value is not None else [interval["minimum"], interval["maximum"]]
    if interval and interval["minimum"] > interval["maximum"]:
        errors.append("measurement range minimum exceeds maximum")
    statistic = measurement["statistic"]
    if statistic == "proportion" and any(not 0 <= number <= 1 for number in values):
        errors.append("proportion must be in [0, 1]")
    if statistic == "percent" and any(not 0 <= number <= 100 for number in values):
        errors.append("percent must be in [0, 100]")
    if statistic == "count" and any(number < 0 or int(number) != number for number in values):
        errors.append("count must be a nonnegative integer")
    scale = measurement["scale"]
    if scale and (
        scale["minimum"] >= scale["maximum"]
        or any(not scale["minimum"] <= number <= scale["maximum"] for number in values)
    ):
        errors.append("invalid measurement scale or value outside scale")
    period = measurement["period"]
    if period:
        if period["start"] and period["end"] and period["start"] > period["end"]:
            errors.append("period starts after it ends")
        future = (
            (period["start"] and period["start"] > as_of)
            or (period["end"] and period["end"] > as_of)
        ) or (
            period["label"].isdigit()
            and len(period["label"]) == 4
            and int(period["label"]) > int(as_of[:4])
        )
        if future and measurement["temporal_status"] == "historical":
            errors.append("future measurements cannot be historical")
    return errors


def _cyclic_nodes(adjacency: dict[str, list[str]]) -> set[str]:
    """Return participants in cycles, without relying on Python recursion depth."""
    cyclic = set()
    for start in adjacency:
        pending = list(adjacency[start])
        seen = set()
        while pending:
            current = pending.pop()
            if current == start:
                cyclic.add(start)
                break
            if current not in seen:
                seen.add(current)
                pending.extend(adjacency.get(current, []))
    return cyclic


def validate_bundle(bundle: dict | GraphBundle) -> list[str]:
    """Check structure and graph rules; errors contain locations, never source text."""
    try:
        data = bundle.model_dump(mode="json") if isinstance(bundle, GraphBundle) else bundle
        payload = json.dumps(data, allow_nan=False)
        parsed = GraphBundle.model_validate_json(payload)
    except ValidationError as error:
        return [
            f"schema/{'/'.join(map(str, detail['loc']))}: violates {detail['type']}"
            for detail in error.errors(include_input=False, include_context=False)
        ]
    except (TypeError, ValueError):
        return ["schema/: input must be a finite JSON object"]

    bundle = parsed.model_dump(mode="json")
    relations = RELATIONSHIPS
    errors = []
    nodes = {}
    entity_revisions = set()
    entity_types = {}
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    edge_ids = set()
    edge_triples = set()
    dedup_keys = set()

    for node in bundle["nodes"]:
        node_id = node["id"]
        if node_id in nodes:
            errors.append(f"{node_id}: duplicate node id")
        nodes[node_id] = node
        key = (node["entity_key"], node["revision"])
        if key in entity_revisions:
            errors.append(f"{node_id}: duplicate logical entity revision")
        entity_revisions.add(key)
        previous_type = entity_types.setdefault(node["entity_key"], node["type"])
        if previous_type != node["type"]:
            errors.append(f"{node_id}: a logical entity cannot change type")

    for edge in bundle["edges"]:
        if edge["id"] in edge_ids:
            errors.append(f"{edge['id']}: duplicate edge id")
        edge_ids.add(edge["id"])
        triple = (edge["type"], edge["source_id"], edge["target_id"])
        if triple in edge_triples:
            errors.append(f"{edge['id']}: duplicate relationship between the same revisions")
        edge_triples.add(triple)
        source = nodes.get(edge["source_id"])
        target = nodes.get(edge["target_id"])
        if source is None or target is None:
            errors.append(f"{edge['id']}: dangling relationship endpoint")
            continue
        outgoing[source["id"]].append(edge)
        incoming[target["id"]].append(edge)
        rule = relations[edge["type"]]
        if source["type"] not in rule.source_types or target["type"] not in rule.target_types:
            errors.append(
                f"{edge['id']}: invalid {source['type']} -> {target['type']} relationship"
            )
            outgoing[source["id"]].pop()
            incoming[target["id"]].pop()
            continue
        if (
            edge["type"] == "DERIVED_FROM"
            and source["type"] in {"Signal", "CatalogItem"}
            and target["type"] != "Evidence"
        ):
            errors.append(f"{edge['id']}: a {source['type']} must derive directly from Evidence")
        if edge["type"] == "SUPERSEDES":
            if source["type"] != target["type"] or source["entity_key"] != target["entity_key"]:
                errors.append(f"{edge['id']}: SUPERSEDES must preserve the logical entity and type")
            if source["revision"] <= target["revision"]:
                errors.append(f"{edge['id']}: SUPERSEDES must point to an older revision")
        if edge["type"] == "COMPETES_WITH" and source["id"] == target["id"]:
            errors.append(f"{edge['id']}: a model cannot compete with itself")
        if edge["type"] in {
            "DERIVED_FROM",
            "SUPPORTS",
            "CHALLENGES",
            "JUSTIFIED_BY",
            "ADDRESSES",
            "BASELINED_ON",
            "DESCRIBES",
            "INCLUDES",
        }:
            source_context = source["properties"].get("context")
            target_context = target["properties"].get("context")
            if source_context and target_context:
                transferred = any(
                    set(source_context[key]) != set(target_context[key])
                    for key in ("vehicle_model_ids", "market_ids", "country_codes", "engine_types")
                )
                if transferred and not edge["context_transfer"]:
                    errors.append(f"{edge['id']}: scope transfer requires an explicit explanation")

    def targets(node_id, relation):
        return [
            nodes[e["target_id"]]
            for e in outgoing[node_id]
            if e["type"] == relation and e["target_id"] in nodes
        ]

    def sources(node_id, relation):
        return [
            nodes[e["source_id"]]
            for e in incoming[node_id]
            if e["type"] == relation and e["source_id"] in nodes
        ]

    def features(node_id):
        return {node["id"] for node in targets(node_id, "CONCERNS")}

    def document_ids(node_id):
        return {
            source["id"]
            for evidence in targets(node_id, "DERIVED_FROM")
            if evidence["type"] == "Evidence"
            for source in targets(evidence["id"], "IN_SOURCE")
            if source["type"] == "SourceDocument"
        }

    includes = {
        node_id: [child["id"] for child in targets(node_id, "INCLUDES")]
        for node_id, node in nodes.items()
        if node["type"] == "CatalogItem"
    }
    variants = {
        node_id: [parent["id"] for parent in targets(node_id, "IS_VARIANT_OF")]
        for node_id, node in nodes.items()
        if node["type"] == "VehicleModel"
    }
    for node_id in sorted(_cyclic_nodes(includes)):
        errors.append(f"{node_id}: cyclic package membership")
    for node_id in sorted(_cyclic_nodes(variants)):
        errors.append(f"{node_id}: cyclic variant ancestry")

    def family_model_ids(model_id):
        seen, pending = set(), [model_id]
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                pending.extend(variants.get(current, []))
        return seen

    def check_conditions(node_id, conditions, source_documents=None):
        for index, condition in enumerate(conditions):
            references = condition["catalog_item_ids"]
            needs_references = condition["kind"] in {"requires_all", "requires_any", "excludes"}
            if needs_references != bool(references):
                errors.append(f"{node_id}: condition {index} has invalid catalog item references")
            for reference in references:
                item = nodes.get(reference)
                if item is None or item["type"] != "CatalogItem":
                    errors.append(f"{node_id}: invalid condition CatalogItem reference {reference}")
                elif reference == node_id:
                    errors.append(f"{node_id}: a catalog condition cannot reference itself")
                elif source_documents is not None and document_ids(reference) != source_documents:
                    errors.append(f"{node_id}: catalog condition crosses source editions")

    def reaches_evidence(node_id, active=None):
        active = set() if active is None else active
        if node_id in active:
            return False
        node = nodes[node_id]
        if node["type"] == "Evidence":
            return len(targets(node_id, "IN_SOURCE")) == 1
        if node["type"] in {"Signal", "CatalogItem"}:
            inputs = targets(node_id, "DERIVED_FROM")
        elif node["type"] == "Trend":
            inputs = targets(node_id, "DERIVED_FROM")
        elif node["type"] == "CustomerNeed":
            inputs = sources(node_id, "SUPPORTS")
        else:
            return False
        return bool(inputs) and all(reaches_evidence(n["id"], active | {node_id}) for n in inputs)

    for node in nodes.values():
        node_id, kind, props = node["id"], node["type"], node["properties"]
        event_dates = []
        if props.get("provenance"):
            event_dates.append(("created_at", props["provenance"]["created_at"]))
        if kind == "SourceDocument":
            event_dates.append(("retrieved_at", props["retrieved_at"]))
        if kind == "Decision":
            event_dates.append(("decided_at", props["decided_at"]))
        for field, timestamp in event_dates:
            observed_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
            if observed_date.isoformat() > bundle["as_of"]:
                errors.append(f"{node_id}: {field} event date is after bundle as_of")
        context = props.get("context")
        if context:
            for field, expected_type in (
                ("vehicle_model_ids", "VehicleModel"),
                ("market_ids", "Market"),
            ):
                for reference in context[field]:
                    if reference not in nodes or nodes[reference]["type"] != expected_type:
                        errors.append(f"{node_id}: invalid {field} reference {reference}")
            if context["as_of"] and context["as_of"] > bundle["as_of"]:
                errors.append(f"{node_id}: context date is after bundle as_of")

        if kind == "VehicleModel":
            parents = targets(node_id, "IS_VARIANT_OF")
            if len(parents) > 1:
                errors.append(f"{node_id}: variant needs at most one parent model")
            for parent in parents:
                parent_props = parent["properties"]
                if props["variant"] is None or parent_props["variant"] is not None:
                    errors.append(
                        f"{node_id}: IS_VARIANT_OF requires a variant child and family parent"
                    )
                if any(
                    props[field] != parent_props[field]
                    for field in ("brand", "vehicle_line", "generation_code")
                ):
                    errors.append(
                        f"{node_id}: variant and parent must share brand, line, and generation"
                    )

        if kind == "SourceDocument":
            if bundle["purpose"] != "fixture" and props["origin"] == "synthetic":
                errors.append(f"{node_id}: synthetic sources are allowed only in fixtures")
            if props["publication_date"]:
                try:
                    value = props["publication_date"]
                    suffix = {4: "-01-01", 7: "-01", 10: ""}[len(value)]
                    date.fromisoformat(value + suffix)
                except ValueError:
                    errors.append(f"{node_id}: invalid publication date")

        if kind == "Evidence":
            if len(targets(node_id, "IN_SOURCE")) != 1:
                errors.append(f"{node_id}: Evidence needs exactly one IN_SOURCE relationship")
            if props["dedup_key"] in dedup_keys:
                errors.append(
                    f"{node_id}: duplicate Evidence dedup_key; preserve classifications on one record"
                )
            dedup_keys.add(props["dedup_key"])
            measurement = props["measurement"]
            if measurement:
                errors.extend(
                    f"{node_id}: {error}"
                    for error in _measurement_errors(measurement, bundle["as_of"])
                )

        if kind in {"Signal", "Trend", "CustomerNeed", "CatalogItem"} and not reaches_evidence(
            node_id
        ):
            errors.append(f"{node_id}: missing or cyclic evidence chain")

        if kind == "CatalogItem":
            documents = document_ids(node_id)
            if len(documents) != 1:
                errors.append(f"{node_id}: CatalogItem needs exactly one original source edition")
            if any(
                nodes[source_id]["properties"]["source_kind"]
                not in {"product_catalog", "competitor_official"}
                for source_id in documents
            ):
                errors.append(f"{node_id}: CatalogItem needs an original product catalog source")
            check_conditions(node_id, props["conditions"], documents)
            children = targets(node_id, "INCLUDES")
            if children and props["item_kind"] != "package":
                errors.append(f"{node_id}: only a package can include catalog items")
            for child in children:
                if document_ids(child["id"]) != documents:
                    errors.append(f"{node_id}: package membership crosses source editions")

        if kind in {"CustomerNeed", "Requirement"} and not features(node_id):
            errors.append(f"{node_id}: {kind} needs at least one CONCERNS Feature relationship")

        if kind == "Signal":
            allowed_sources = {
                "customer_feedback": {"feedback_dataset"},
                "public_sentiment": {"public_discussion", "editorial_review"},
                "competitor_capability": {
                    "competitor_official",
                    "editorial_review",
                    "product_catalog",
                },
                "product_capability": {
                    "product_catalog",
                    "competitor_official",
                    "editorial_review",
                },
                "study_finding": {"customer_study"},
                "commercial_indicator": {"sales_dataset"},
                "trend_indicator": {"industry_report", "global_indicator", "editorial_review"},
            }
            for evidence in targets(node_id, "DERIVED_FROM"):
                if evidence["type"] != "Evidence":
                    continue
                for source in targets(evidence["id"], "IN_SOURCE"):
                    if (
                        source["type"] == "SourceDocument"
                        and source["properties"]["source_kind"]
                        not in allowed_sources[props["signal_kind"]]
                    ):
                        errors.append(f"{node_id}: source kind does not match signal kind")
            if props["signal_kind"] in {"competitor_capability", "product_capability"}:
                if not context["vehicle_model_ids"]:
                    errors.append(
                        f"{node_id}: product or competitor capability needs a model reference"
                    )
                if not features(node_id):
                    errors.append(
                        f"{node_id}: capability needs at least one CONCERNS Feature relationship"
                    )
                if props["epistemic_status"] != "publisher_claim":
                    errors.append(
                        f"{node_id}: capability must retain publisher_claim epistemic status"
                    )
            capability = props["capability"]
            is_capability = props["signal_kind"] in {"competitor_capability", "product_capability"}
            if capability and not is_capability:
                errors.append(
                    f"{node_id}: only a capability Signal can contain a capability payload"
                )
            if props["public_context"] and props["signal_kind"] != "public_sentiment":
                errors.append(
                    f"{node_id}: only a public_sentiment Signal can contain public_context"
                )
            if capability:
                if capability["variant"] is not None and any(
                    model_id in nodes
                    and nodes[model_id]["type"] == "VehicleModel"
                    and nodes[model_id]["properties"]["variant"] is not None
                    and nodes[model_id]["properties"]["variant"] != capability["variant"]
                    for model_id in context["vehicle_model_ids"]
                ):
                    errors.append(
                        f"{node_id}: capability variant disagrees with the scoped model variant"
                    )
                check_conditions(node_id, capability["conditions"], document_ids(node_id))
                if capability["measurement"]:
                    errors.extend(
                        f"{node_id}: capability measurement: {error}"
                        for error in _measurement_errors(capability["measurement"], bundle["as_of"])
                    )
            described_items = targets(node_id, "DESCRIBES")
            if len(described_items) > 1:
                errors.append(f"{node_id}: a capability Signal describes at most one CatalogItem")
            for item in described_items:
                if props["signal_kind"] not in {"product_capability", "competitor_capability"}:
                    errors.append(f"{node_id}: only a capability Signal can describe a CatalogItem")
                if document_ids(node_id) != document_ids(item["id"]):
                    errors.append(f"{node_id}: described catalog item crosses source editions")

        if kind == "Trend":
            if props["horizon"]["from_year"] > props["horizon"]["to_year"]:
                errors.append(f"{node_id}: invalid trend horizon")
            if props["temporal_status"] in {"forecast", "mixed"} and not targets(
                node_id, "DEPENDS_ON"
            ):
                errors.append(f"{node_id}: projected Trend needs an explicit Assumption")

        if kind == "Requirement":
            launch_year = props["target_launch_year"]
            creation_year = datetime.fromisoformat(
                props["provenance"]["created_at"].replace("Z", "+00:00")
            ).year
            if launch_year is not None and launch_year != creation_year + props["horizon_years"]:
                errors.append(
                    f"{node_id}: target launch year must match requirement creation year plus horizon_years"
                )
            if not context["vehicle_model_ids"] or not context["market_ids"]:
                errors.append(f"{node_id}: Requirement needs baseline models and target markets")
            for model_id in context["vehicle_model_ids"]:
                model = nodes.get(model_id)
                if (
                    model
                    and model["type"] == "VehicleModel"
                    and model["properties"]["brand"].casefold() != "bmw"
                ):
                    errors.append(f"{node_id}: successor baseline must be a BMW model")
            needs, justifications = targets(node_id, "ADDRESSES"), targets(node_id, "JUSTIFIED_BY")
            if not needs or not all(reaches_evidence(n["id"]) for n in needs):
                errors.append(f"{node_id}: Requirement must address an evidenced CustomerNeed")
            if not justifications or not all(reaches_evidence(n["id"]) for n in justifications):
                errors.append(f"{node_id}: Requirement needs traceable justifications")
            if not targets(node_id, "DEPENDS_ON"):
                errors.append(f"{node_id}: successor proposal needs a forward-looking Assumption")
            baselines = targets(node_id, "BASELINED_ON")
            status, intent = props["baseline_status"], props["change_intent"]
            if intent in {"improve", "retain", "remove"} and status != "known_present":
                errors.append(
                    f"{node_id}: improve, retain, or remove requires a known_present baseline"
                )
            if intent == "introduce" and status == "known_present":
                errors.append(f"{node_id}: introduce cannot use a known_present baseline")
            if status in {"known_present", "known_absent"} and not baselines:
                errors.append(
                    f"{node_id}: known baseline status requires explicit BASELINED_ON evidence"
                )
            for baseline in baselines:
                baseline_props = baseline["properties"]
                if baseline_props["signal_kind"] != "product_capability":
                    errors.append(
                        f"{node_id}: BASELINED_ON must target a product_capability Signal"
                    )
                if not reaches_evidence(baseline["id"]):
                    errors.append(f"{node_id}: baseline needs a traceable evidence chain")
                if not features(node_id) & features(baseline["id"]):
                    errors.append(f"{node_id}: baseline must share a canonical Feature")
                model_ids = baseline_props["context"]["vehicle_model_ids"]
                if not model_ids or any(
                    model_id not in nodes
                    or nodes[model_id]["type"] != "VehicleModel"
                    or nodes[model_id]["properties"]["brand"].casefold() != "bmw"
                    or not family_model_ids(model_id) & set(context["vehicle_model_ids"])
                    for model_id in model_ids
                ):
                    errors.append(
                        f"{node_id}: baseline capability must describe the BMW baseline model or variant"
                    )
                capability = baseline_props["capability"]
                availability = capability["availability"] if capability else "unknown"
                if status == "known_present" and availability not in {
                    "standard",
                    "optional",
                    "available_unspecified",
                }:
                    errors.append(
                        f"{node_id}: known_present requires an explicitly available capability"
                    )
                if status == "known_absent" and availability != "unavailable":
                    errors.append(
                        f"{node_id}: known_absent requires explicit unavailable capability evidence"
                    )
            if node["revision"] > 1:
                previous = targets(node_id, "SUPERSEDES")
                if len(previous) != 1 or previous[0]["revision"] != node["revision"] - 1:
                    errors.append(
                        f"{node_id}: Requirement revision must SUPERSEDES its consecutive previous revision"
                    )
            for criterion in props["acceptance_criteria"]:
                if criterion["target"] is not None and any(
                    criterion[field] is None for field in ("metric", "operator", "unit")
                ):
                    errors.append(f"{node_id}: numeric criterion needs metric, operator, and unit")
                if (
                    criterion["basis"] == "evidence_supported_target"
                    and not criterion["supporting_evidence_ids"]
                ):
                    errors.append(f"{node_id}: evidence-supported target needs explicit evidence")
                for evidence_id in criterion["supporting_evidence_ids"]:
                    if evidence_id not in nodes or nodes[evidence_id]["type"] != "Evidence":
                        errors.append(f"{node_id}: invalid criterion evidence reference")
                if (
                    criterion["basis"] == "human_set_target"
                    and props["provenance"]["actor_type"] != "human"
                ):
                    errors.append(f"{node_id}: human-set target requires recorded human authorship")
                if (
                    criterion["verification_method"] != "to_be_defined"
                    and not criterion["test_conditions"]
                ):
                    errors.append(f"{node_id}: verified criterion needs explicit test conditions")

        if kind == "Decision":
            reviewed = targets(node_id, "REVIEWS")
            if len(reviewed) != 1:
                errors.append(f"{node_id}: Decision must review exactly one Requirement")
            elif props["requirement_revision"] != reviewed[0]["revision"]:
                errors.append(f"{node_id}: Decision targets the wrong requirement revision")
            elif reviewed[0]["type"] == "Requirement" and datetime.fromisoformat(
                props["decided_at"].replace("Z", "+00:00")
            ) < datetime.fromisoformat(
                reviewed[0]["properties"]["provenance"]["created_at"].replace("Z", "+00:00")
            ):
                errors.append(f"{node_id}: Decision predates the requirement revision")
            if (props["action"] == "set_priority") != (props["priority"] is not None):
                errors.append(f"{node_id}: priority is required only for set_priority")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", nargs="+", type=Path)
    args = parser.parse_args()
    failed = False
    for path in args.bundles:
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
            errors = validate_bundle(bundle)
        except (OSError, ValueError) as error:
            errors = [f"{type(error).__name__}: could not read a JSON bundle"]
        if errors:
            failed = True
            print(f"INVALID {path}")
            for error in errors:
                print(f"  {error}")
        else:
            print(
                f"VALID {path}: {len(bundle['nodes'])} nodes, {len(bundle['edges'])} relationships"
            )
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
