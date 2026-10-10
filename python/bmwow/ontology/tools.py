"""Deterministic ontology tools, independent of agent orchestration and storage.

Read operations require a valid closed snapshot. Returned slices deliberately are
not GraphBundles: they may omit unrelated references and report truncation. Service
code supplies actor binding and snapshot preconditions outside model arguments.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .models import (
    ONTOLOGY_VERSION,
    ContractModel,
    CountryCode,
    Edge,
    EngineType,
    GraphBundle,
    Id,
    Node,
    NodeType,
    RelationshipType,
    Requirement,
    SignalKind,
    Text,
    UniqueList,
)
from .validation import validate_bundle

Limit = Annotated[int, Field(ge=1, le=100)]


class OntologyQuery(ContractModel):
    """Find objects using explicit references; filters are ANDed across dimensions."""

    node_types: UniqueList[NodeType] = Field(
        default_factory=list, description="Empty means all types."
    )
    ids: UniqueList[Id] = Field(
        default_factory=list, description="Exact revision IDs, if specified."
    )
    vehicle_model_ids: UniqueList[Id] = Field(
        default_factory=list,
        description="Match explicit context references; no generation or variant inference.",
    )
    market_ids: UniqueList[Id] = Field(
        default_factory=list,
        description="Match explicit context references; unknown scope never matches a requested market.",
    )
    country_codes: UniqueList[CountryCode] = Field(
        default_factory=list,
        description="Match explicitly observed countries without assigning market membership.",
    )
    engine_types: UniqueList[EngineType] = Field(
        default_factory=list,
        description="Match explicit engine-type context; unknown is not ICE, PHEV, or BEV.",
    )
    feature_ids: UniqueList[Id] = Field(
        default_factory=list, description="Match outgoing CONCERNS references."
    )
    signal_kinds: UniqueList[SignalKind] = Field(default_factory=list)
    temporal_status: (
        Literal["historical", "source_reported_future", "forecast", "unknown", "observed", "mixed"]
        | None
    ) = Field(
        default=None,
        description="Match direct measurement or Trend status. Study/commercial Signals inherit only when every direct Evidence measurement agrees; missing or conflicting inputs are unknown.",
    )
    latest_only: bool = Field(
        default=True,
        description="Select the highest revision of each logical entity before applying filters.",
    )
    limit: Limit = 20
    offset: Annotated[int, Field(ge=0, le=10000)] = 0


class QueryResult(ContractModel):
    nodes: list[Node]
    total: int
    offset: int
    truncated: bool


class TraversalQuery(ContractModel):
    """Traverse stored relationships in either direction without inventing inverse edges."""

    node_id: Id
    relationship_types: UniqueList[RelationshipType] = Field(default_factory=list)
    direction: Literal["incoming", "outgoing", "both"] = "both"
    max_depth: Annotated[int, Field(ge=1, le=4)] = 1
    max_nodes: Annotated[int, Field(ge=2, le=200)] = 50


class TraceQuery(ContractModel):
    """Retrieve support, challenges, baselines, premises, and original evidence."""

    node_id: Id
    max_depth: Annotated[int, Field(ge=1, le=12)] = 8
    max_nodes: Annotated[int, Field(ge=2, le=500)] = 100


class ObjectReference(ContractModel):
    """A stored property reference; this is not an ontology relationship edge."""

    source_id: Id
    field: Text
    target_id: Id


class GraphSlice(ContractModel):
    root_id: Id
    nodes: list[Node]
    edges: list[Edge]
    references: list[ObjectReference] = Field(default_factory=list)
    truncated: bool


class RequirementQuery(ContractModel):
    requirement_id: Id = Field(
        description="An exact Requirement revision ID, not a logical entity key."
    )
    max_nodes: Annotated[int, Field(ge=2, le=500)] = 100


class ReviewState(ContractModel):
    status: Literal["unreviewed", "approved", "rejected", "changes_requested", "ambiguous"]
    decision_ids: list[Id]
    priority: int | None
    priority_decision_ids: list[Id]


class RequirementDossier(ContractModel):
    requirement: Requirement
    trace: GraphSlice
    baseline_ids: list[Id]
    assumption_ids: list[Id]
    decisions: list[Node]
    review: ReviewState
    truncated: bool


class ComparisonQuery(ContractModel):
    node_ids: Annotated[UniqueList[Id], Field(min_length=2, max_length=20)] = Field(
        description="Evidence or capability Signal objects with measurements; no implicit unit conversion."
    )


class ComparisonReadiness(ContractModel):
    node_ids: list[Id]
    status: Literal["ready_for_review", "not_ready"]
    blockers: list[Text]
    cautions: list[Text]


class ProposalEdge(Edge):
    type: Literal[
        "CONCERNS",
        "ADDRESSES",
        "JUSTIFIED_BY",
        "DEPENDS_ON",
        "BASELINED_ON",
        "SUPERSEDES",
        "SUPPORTS",
        "CHALLENGES",
    ]


class RequirementProposal(ContractModel):
    """One software-authored Requirement and links to existing objects; no edits or decisions."""

    requirement: Requirement
    edges: Annotated[list[ProposalEdge], Field(min_length=1, max_length=100)]


class ProposalIssue(ContractModel):
    code: Literal[
        "invalid_base",
        "invalid_structure",
        "stale_snapshot",
        "identity_collision",
        "revision_conflict",
        "disallowed_change",
        "invalid_graph",
    ]
    message: Text


class ProposalResult(ContractModel):
    accepted: bool = Field(
        description="Candidate passed validation; this does not mean human approval or persistence."
    )
    base_fingerprint: Text | None
    errors: list[ProposalIssue]
    candidate: GraphBundle | None


def _parse(model, value):
    data = value.model_dump(mode="json") if isinstance(value, ContractModel) else value
    return model.model_validate_json(json.dumps(data, allow_nan=False))


def _closed(bundle: dict | GraphBundle) -> GraphBundle:
    errors = validate_bundle(bundle)
    if errors:
        raise ValueError("Invalid closed ontology snapshot: " + "; ".join(errors))
    return _parse(GraphBundle, bundle)


def _indices(bundle: GraphBundle):
    nodes = {node.id: node for node in bundle.nodes}
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for edge in sorted(bundle.edges, key=lambda item: (item.type, item.id)):
        outgoing[edge.source_id].append(edge)
        incoming[edge.target_id].append(edge)
    return nodes, outgoing, incoming


def _context(node):
    context = getattr(node.properties, "context", None)
    return context.model_dump(mode="json") if context else {}


def _measurement(node):
    measurement = getattr(node.properties, "measurement", None)
    capability = getattr(node.properties, "capability", None)
    return measurement or (capability.measurement if capability else None)


def query_nodes(bundle: dict | GraphBundle, query: OntologyQuery | dict) -> QueryResult:
    """Retrieve a deterministic page; an OR applies within each reference list.

    Study/commercial Signals inherit a temporal status only when every direct
    Evidence input has a measurement and all their temporal statuses agree.
    Missing or mixed inputs remain unknown; no first-input shortcut is applied.
    """
    bundle, query = _closed(bundle), _parse(OntologyQuery, query)
    nodes, outgoing, _ = _indices(bundle)
    latest = {}
    for node in nodes.values():
        latest[node.entity_key] = max(latest.get(node.entity_key, 0), node.revision)
    matches = []
    for node in sorted(nodes.values(), key=lambda item: item.id):
        if query.latest_only and node.revision != latest[node.entity_key]:
            continue
        if query.node_types and node.type not in query.node_types:
            continue
        if query.ids and node.id not in query.ids:
            continue
        context = _context(node)
        if any(
            requested and not set(requested).intersection(context.get(field, []))
            for field, requested in (
                ("vehicle_model_ids", query.vehicle_model_ids),
                ("market_ids", query.market_ids),
                ("country_codes", query.country_codes),
                ("engine_types", query.engine_types),
            )
        ):
            continue
        if query.feature_ids and not any(
            edge.type == "CONCERNS" and edge.target_id in query.feature_ids
            for edge in outgoing[node.id]
        ):
            continue
        if (
            query.signal_kinds
            and getattr(node.properties, "signal_kind", None) not in query.signal_kinds
        ):
            continue
        measurement = _measurement(node)
        temporal = getattr(node.properties, "temporal_status", None) or (
            measurement.temporal_status if measurement else None
        )
        if measurement is None and getattr(node.properties, "signal_kind", None) in {
            "study_finding",
            "commercial_indicator",
        }:
            inputs = [
                nodes[edge.target_id] for edge in outgoing[node.id] if edge.type == "DERIVED_FROM"
            ]
            statuses = {
                input_measurement.temporal_status
                for item in inputs
                if (input_measurement := _measurement(item)) is not None
            }
            temporal = (
                next(iter(statuses))
                if inputs
                and len(statuses) == 1
                and all(_measurement(item) is not None for item in inputs)
                else "unknown"
            )
        if query.temporal_status and query.temporal_status != temporal:
            continue
        matches.append(node)
    return QueryResult(
        nodes=matches[query.offset : query.offset + query.limit],
        total=len(matches),
        offset=query.offset,
        truncated=query.offset + query.limit < len(matches),
    )


def _walk(
    bundle: GraphBundle,
    root_id: str,
    select: Callable,
    max_depth: int,
    max_nodes: int,
    property_references: Callable | None = None,
) -> GraphSlice:
    nodes, outgoing, incoming = _indices(bundle)
    if root_id not in nodes:
        raise ValueError(f"Unknown ontology object: {root_id}")
    visited, edges, references, truncated = {root_id}, {}, {}, False
    queue = deque([(root_id, 0)])
    while queue:
        node_id, depth = queue.popleft()
        selected = select(nodes[node_id], outgoing[node_id], incoming[node_id])
        fields = property_references(nodes[node_id]) if property_references else []
        choices = [
            (edge.target_id if edge.source_id == node_id else edge.source_id, edge)
            for edge in selected
        ]
        choices += [(reference.target_id, reference) for reference in fields]
        for neighbor, item in choices:
            collection = edges if isinstance(item, Edge) else references
            key = (
                item.id if isinstance(item, Edge) else (item.source_id, item.field, item.target_id)
            )
            if key not in collection and len(edges) + len(references) >= min(max_nodes * 4, 1000):
                truncated = True
                continue
            if depth >= max_depth:
                if key not in collection:
                    truncated = True
                continue
            if neighbor not in visited:
                if len(visited) >= max_nodes:
                    truncated = True
                    continue
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
            collection[key] = item
    return GraphSlice(
        root_id=root_id,
        nodes=[nodes[key] for key in sorted(visited)],
        edges=[edges[key] for key in sorted(edges)],
        references=[references[key] for key in sorted(references)],
        truncated=truncated,
    )


def traverse(bundle: dict | GraphBundle, query: TraversalQuery | dict) -> GraphSlice:
    """Read incoming, outgoing, or both directions; preserve stored edge orientation."""
    bundle, query = _closed(bundle), _parse(TraversalQuery, query)

    def select(node, outgoing, incoming):
        choices = ([] if query.direction == "incoming" else outgoing) + (
            [] if query.direction == "outgoing" else incoming
        )
        return [
            edge
            for edge in choices
            if not query.relationship_types or edge.type in query.relationship_types
        ]

    return _walk(bundle, query.node_id, select, query.max_depth, query.max_nodes)


def trace_evidence(bundle: dict | GraphBundle, query: TraceQuery | dict) -> GraphSlice:
    """Follow all reasoning branches, including challenges to needs and assumptions."""
    bundle, query = _closed(bundle), _parse(TraceQuery, query)
    downstream = {
        "Requirement": {"JUSTIFIED_BY", "ADDRESSES", "BASELINED_ON", "DEPENDS_ON", "CONCERNS"},
        "CustomerNeed": {"DEPENDS_ON", "CONCERNS"},
        "Trend": {"DERIVED_FROM", "DEPENDS_ON", "CONCERNS"},
        "Signal": {"DERIVED_FROM", "DESCRIBES", "CONCERNS"},
        "CatalogItem": {"DERIVED_FROM", "INCLUDES", "CONCERNS"},
        "Evidence": {"IN_SOURCE"},
        "VehicleModel": {"IS_VARIANT_OF"},
    }

    def select(node, outgoing, incoming):
        return [edge for edge in incoming if edge.type in {"CHALLENGES", "SUPPORTS"}] + [
            edge for edge in outgoing if edge.type in downstream.get(node.type, set())
        ]

    def property_references(node):
        fields = []
        context = _context(node)
        for field in ("vehicle_model_ids", "market_ids"):
            fields.extend(
                (f"properties.context.{field}", target) for target in context.get(field, [])
            )
        for index, criterion in enumerate(getattr(node.properties, "acceptance_criteria", [])):
            fields.extend(
                (f"properties.acceptance_criteria[{index}].supporting_evidence_ids", target)
                for target in criterion.supporting_evidence_ids
            )
        owners = [("properties", node.properties)]
        capability = getattr(node.properties, "capability", None)
        if capability:
            owners.append(("properties.capability", capability))
        for prefix, owner in owners:
            for index, condition in enumerate(getattr(owner, "conditions", [])):
                fields.extend(
                    (f"{prefix}.conditions[{index}].catalog_item_ids", target)
                    for target in condition.catalog_item_ids
                )
        return [
            ObjectReference(source_id=node.id, field=field, target_id=target)
            for field, target in fields
        ]

    return _walk(
        bundle, query.node_id, select, query.max_depth, query.max_nodes, property_references
    )


def _review(decisions: list) -> ReviewState:
    reviews = [
        node
        for node in decisions
        if node.properties.action in {"approve", "reject", "request_changes"}
    ]
    priorities = [node for node in decisions if node.properties.action == "set_priority"]
    latest_review = max((node.properties.decided_at for node in reviews), default=None)
    latest_priority = max((node.properties.decided_at for node in priorities), default=None)
    current = [node for node in reviews if node.properties.decided_at == latest_review]
    priority_events = [node for node in priorities if node.properties.decided_at == latest_priority]
    actions = {node.properties.action for node in current}
    values = {node.properties.priority for node in priority_events}
    status = (
        "unreviewed"
        if not actions
        else "ambiguous"
        if len(actions) > 1
        else {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}[
            next(iter(actions))
        ]
    )
    return ReviewState(
        status=status,
        decision_ids=sorted(node.id for node in current),
        priority=next(iter(values)) if len(values) == 1 else None,
        priority_decision_ids=sorted(node.id for node in priority_events),
    )


def get_requirement_context(
    bundle: dict | GraphBundle, query: RequirementQuery | dict
) -> RequirementDossier:
    """Assemble a bounded dossier; review applies only to the requested revision."""
    bundle, query = _closed(bundle), _parse(RequirementQuery, query)
    nodes, outgoing, incoming = _indices(bundle)
    requirement = nodes.get(query.requirement_id)
    if requirement is None or requirement.type != "Requirement":
        raise ValueError(f"Expected an exact Requirement revision: {query.requirement_id}")
    decisions = sorted(
        (nodes[edge.source_id] for edge in incoming[requirement.id] if edge.type == "REVIEWS"),
        key=lambda node: (node.properties.decided_at, node.id),
    )
    trace = trace_evidence(bundle, TraceQuery(node_id=requirement.id, max_nodes=query.max_nodes))
    baselines = sorted(
        edge.target_id for edge in outgoing[requirement.id] if edge.type == "BASELINED_ON"
    )
    review = _review(decisions)
    review = review.model_copy(
        update={
            "decision_ids": review.decision_ids[: query.max_nodes],
            "priority_decision_ids": review.priority_decision_ids[: query.max_nodes],
        }
    )
    return RequirementDossier(
        requirement=requirement,
        trace=trace,
        baseline_ids=baselines[: query.max_nodes],
        assumption_ids=sorted(node.id for node in trace.nodes if node.type == "Assumption"),
        decisions=decisions[-query.max_nodes :],
        review=review,
        truncated=trace.truncated
        or len(decisions) > query.max_nodes
        or len(baselines) > query.max_nodes,
    )


def comparison_readiness(
    bundle: dict | GraphBundle, query: ComparisonQuery | dict
) -> ComparisonReadiness:
    """Flag incompatible or underspecified quantities; never normalize units or surveys."""
    bundle, query = _closed(bundle), _parse(ComparisonQuery, query)
    nodes, _, _ = _indices(bundle)
    measurements, blockers, cautions = [], [], []
    for node_id in query.node_ids:
        node = nodes.get(node_id)
        if node is None:
            blockers.append(f"{node_id}: object does not exist")
            continue
        measurement = _measurement(node)
        if measurement is None:
            blockers.append(f"{node_id}: no measurement")
            continue
        measurements.append(measurement.model_dump(mode="json"))
        if measurement.temporal_status == "unknown":
            blockers.append(f"{node_id}: unknown temporal status")
        if measurement.statistic in {"mean", "index"} and measurement.scale is None:
            blockers.append(f"{node_id}: scale bounds are unknown")
        if measurement.statistic in {"mean", "proportion", "percent", "index"} and (
            measurement.population is None or measurement.sample_size is None
        ):
            blockers.append(f"{node_id}: survey population or sample size is unknown")
        if measurement.statistic in {"proportion", "percent"} and measurement.denominator is None:
            blockers.append(f"{node_id}: denominator is unknown")
        if measurement.comparison_basis is None:
            blockers.append(f"{node_id}: comparison basis is unknown")
        if measurement.notes:
            cautions.append(f"{node_id}: preserve measurement notes and limitations during review")
    if len(measurements) == len(query.node_ids):
        for field in (
            "metric",
            "unit",
            "statistic",
            "temporal_status",
            "scale",
            "test_standard",
            "conditions",
            "question",
            "response_category",
            "comparison_basis",
            "population",
        ):
            values = {
                json.dumps(measurement.get(field), sort_keys=True) for measurement in measurements
            }
            if len(values) > 1:
                blockers.append(
                    f"Measurements differ in {field}; no implicit harmonization is applied"
                )
        if any(measurement.get("value_range") is not None for measurement in measurements) and any(
            measurement.get("value") is not None for measurement in measurements
        ):
            blockers.append("Scalar and range measurements need an explicit comparison rule")
    capabilities = [
        (node_id, getattr(nodes[node_id].properties, "capability", None))
        for node_id in query.node_ids
        if node_id in nodes
    ]
    if any(capability is not None for _, capability in capabilities):
        if any(capability is None for _, capability in capabilities):
            cautions.append(
                "Some objects have no capability-availability metadata; review configuration applicability"
            )
        populated = [capability for _, capability in capabilities if capability is not None]
        for field in ("availability", "variant", "conditions"):
            if (
                len(
                    {
                        json.dumps(capability.model_dump(mode="json")[field], sort_keys=True)
                        for capability in populated
                    }
                )
                > 1
            ):
                blockers.append(
                    f"Capabilities differ in {field}; configuration alternatives are not interchangeable"
                )
        if any(capability.availability == "unknown" for capability in populated):
            cautions.append("Capability availability is unknown for one or more objects")
    contexts = [_context(nodes[node_id]) for node_id in query.node_ids if node_id in nodes]
    for node_id in query.node_ids:
        if node_id not in nodes:
            continue
        context = _context(nodes[node_id])
        for field in ("vehicle_model_ids", "market_ids", "country_codes", "engine_types", "as_of"):
            if not context.get(field):
                cautions.append(
                    f"{node_id}: {field} scope is unknown; do not assume universal applicability"
                )
    for field in ("vehicle_model_ids", "market_ids", "country_codes", "engine_types", "as_of"):
        if len({json.dumps(context.get(field), sort_keys=True) for context in contexts}) > 1:
            cautions.append(f"Contexts differ in {field}; review applicability explicitly")
    if measurements and any(
        measurement.get("period") != measurements[0].get("period") for measurement in measurements
    ):
        cautions.append(
            "Observation periods differ; do not equate periods or extrapolate automatically"
        )
    return ComparisonReadiness(
        node_ids=query.node_ids,
        status="not_ready" if blockers else "ready_for_review",
        blockers=blockers,
        cautions=cautions,
    )


def snapshot_fingerprint(bundle: dict | GraphBundle) -> str:
    """Content fingerprint, insensitive to object/link ordering; not authentication."""
    data = _closed(bundle).model_dump(mode="json")
    data["nodes"].sort(key=lambda node: node["id"])
    data["edges"].sort(key=lambda edge: edge["id"])
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_proposal(
    bundle: dict | GraphBundle,
    proposal: RequirementProposal | dict,
    *,
    expected_fingerprint: str | None = None,
    actor_id: str | None = None,
) -> ProposalResult:
    """Validate an append-only candidate; caller authenticates identity and persists atomically."""
    errors = []

    def issue(code, message):
        errors.append(ProposalIssue(code=code, message=message))

    base_errors = validate_bundle(bundle)
    if base_errors:
        return ProposalResult(
            accepted=False,
            base_fingerprint=None,
            errors=[ProposalIssue(code="invalid_base", message=message) for message in base_errors],
            candidate=None,
        )
    base = _closed(bundle)
    fingerprint = snapshot_fingerprint(base)
    if expected_fingerprint is not None and expected_fingerprint != fingerprint:
        issue(
            "stale_snapshot",
            "Snapshot changed since the service established the proposal precondition",
        )
    try:
        proposal = _parse(RequirementProposal, proposal)
    except (ValidationError, ValueError, TypeError):
        issue(
            "invalid_structure",
            "Proposal must contain exactly one typed Requirement and allowed relationships",
        )
        return ProposalResult(
            accepted=False, base_fingerprint=fingerprint, errors=errors, candidate=None
        )
    requirement = proposal.requirement
    nodes, _, _ = _indices(base)
    edge_ids = {edge.id for edge in base.edges}
    if requirement.id in nodes:
        issue("identity_collision", "An existing object ID cannot be replaced")
    for edge in proposal.edges:
        if edge.id in edge_ids:
            issue(
                "identity_collision", f"{edge.id}: an existing relationship ID cannot be replaced"
            )
        outgoing = edge.source_id == requirement.id
        incoming = edge.target_id == requirement.id
        allowed = (
            outgoing
            and edge.type not in {"SUPPORTS", "CHALLENGES"}
            or incoming
            and edge.type in {"SUPPORTS", "CHALLENGES"}
        )
        other_id = edge.target_id if outgoing else edge.source_id
        if not allowed or other_id not in nodes:
            issue(
                "disallowed_change",
                f"{edge.id}: proposal links must connect the proposed Requirement to existing objects in the permitted direction",
            )
    provenance = requirement.properties.provenance
    if provenance.actor_type != "software":
        issue("disallowed_change", "Agent proposals cannot claim human authorship")
    if actor_id is not None and provenance.actor_id != actor_id:
        issue("disallowed_change", "Recorded proposal actor does not match the service-bound actor")
    if any(
        criterion.basis == "human_set_target"
        for criterion in requirement.properties.acceptance_criteria
    ):
        issue("disallowed_change", "Agent proposals cannot set human-authored acceptance targets")
    history = [node for node in base.nodes if node.entity_key == requirement.entity_key]
    supersedes = [edge for edge in proposal.edges if edge.type == "SUPERSEDES"]
    if history:
        latest = max(history, key=lambda node: node.revision)
        if latest.type != "Requirement" or requirement.revision != latest.revision + 1:
            issue(
                "revision_conflict",
                "A proposal must be the next revision of the same Requirement entity",
            )
        if len(supersedes) != 1 or supersedes[0].target_id != latest.id:
            issue(
                "revision_conflict",
                "A revised proposal must SUPERSEDES exactly the latest Requirement revision",
            )
    elif requirement.revision != 1 or supersedes:
        issue(
            "revision_conflict", "A new Requirement entity starts at revision 1 without SUPERSEDES"
        )
    if errors:
        return ProposalResult(
            accepted=False, base_fingerprint=fingerprint, errors=errors, candidate=None
        )
    candidate_data = base.model_dump(mode="json")
    candidate_data["nodes"].append(requirement.model_dump(mode="json"))
    candidate_data["edges"].extend(edge.model_dump(mode="json") for edge in proposal.edges)
    for message in validate_bundle(candidate_data):
        issue("invalid_graph", message)
    candidate = None if errors else _parse(GraphBundle, candidate_data)
    return ProposalResult(
        accepted=not errors, base_fingerprint=fingerprint, errors=errors, candidate=candidate
    )


def build_agent_contracts() -> dict:
    """Export narrow tool inputs and portable results; complete graphs remain separate."""

    def schema(model, mode):
        result = model.model_json_schema(mode=mode)
        result["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        return result

    return {
        "ontology_version": ONTOLOGY_VERSION,
        "x-generated-by": "uv run bmwow-schema; do not edit this file by hand",
        "description": "Framework-neutral agent inputs; graph access, actor identity, and snapshot preconditions are service-bound. Structure validation never replaces merged graph validation.",
        "inputs": {
            name: schema(model, "validation")
            for name, model in {
                "query_nodes": OntologyQuery,
                "traverse": TraversalQuery,
                "trace_evidence": TraceQuery,
                "get_requirement_context": RequirementQuery,
                "comparison_readiness": ComparisonQuery,
                "validate_proposal": RequirementProposal,
            }.items()
        },
        "outputs": {
            name: schema(model, "serialization")
            for name, model in {
                "query_nodes": QueryResult,
                "traverse": GraphSlice,
                "trace_evidence": GraphSlice,
                "get_requirement_context": RequirementDossier,
                "comparison_readiness": ComparisonReadiness,
                "validate_proposal": ProposalResult,
            }.items()
        },
    }
