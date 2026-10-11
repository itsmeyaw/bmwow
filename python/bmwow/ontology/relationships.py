"""Canonical relationship endpoints and descriptions for validation and export."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RelationshipRule:
    source_types: tuple[str, ...]
    target_types: tuple[str, ...]
    description: str
    inverse_name: str


RELATIONSHIPS = {
    "IN_SOURCE": RelationshipRule(
        ("Evidence",),
        ("SourceDocument",),
        "Locates original evidence in its captured source.",
        "HAS_EVIDENCE",
    ),
    "DERIVED_FROM": RelationshipRule(
        ("Signal", "Trend", "CatalogItem"),
        ("Evidence", "Signal"),
        "Traces an interpretation, catalog item or trend to inputs. Signals and items use Evidence.",
        "DERIVATIONS",
    ),
    "CONCERNS": RelationshipRule(
        ("Signal", "CustomerNeed", "Trend", "Requirement", "CatalogItem"),
        ("Feature",),
        "Associates an interpretation or proposal with a canonical feature.",
        "SUBJECT_OF",
    ),
    "SUPPORTS": RelationshipRule(
        ("Signal", "Trend"),
        ("CustomerNeed", "Requirement", "Assumption"),
        "Provides supporting evidence, with an explicit rationale and scope-transfer explanation.",
        "SUPPORTED_BY",
    ),
    "CHALLENGES": RelationshipRule(
        ("Signal", "Trend"),
        ("CustomerNeed", "Requirement", "Assumption"),
        "Provides opposing or limiting evidence; sentiment alone does not determine this relationship.",
        "CHALLENGED_BY",
    ),
    "ADDRESSES": RelationshipRule(
        ("Requirement",),
        ("CustomerNeed",),
        "States the customer outcome a requirement is intended to deliver.",
        "ADDRESSED_BY",
    ),
    "JUSTIFIED_BY": RelationshipRule(
        ("Requirement",),
        ("Signal", "Trend"),
        "Provides the evidence chain and rationale for a proposed requirement.",
        "JUSTIFIES",
    ),
    "DEPENDS_ON": RelationshipRule(
        ("Requirement", "CustomerNeed", "Trend"),
        ("Assumption",),
        "Makes a forward-looking or inferential premise explicit.",
        "PREMISE_FOR",
    ),
    "REVIEWS": RelationshipRule(
        ("Decision",),
        ("Requirement",),
        "Targets one requirement revision without mutating the proposal or source evidence.",
        "REVIEWED_BY",
    ),
    "COMPETES_WITH": RelationshipRule(
        ("VehicleModel",),
        ("VehicleModel",),
        "A scoped competitive comparison chosen for a market and segment, not assumed from brand alone.",
        "COMPETITOR_OF",
    ),
    "SUPERSEDES": RelationshipRule(
        ("Signal", "CustomerNeed", "Trend", "Assumption", "Requirement", "CatalogItem"),
        ("Signal", "CustomerNeed", "Trend", "Assumption", "Requirement", "CatalogItem"),
        "Links a newer revision to an older revision of the same entity type.",
        "SUPERSEDED_BY",
    ),
    "DESCRIBES": RelationshipRule(
        ("Signal",),
        ("CatalogItem",),
        "Connects one product or competitor capability claim to its catalog-edition item.",
        "DESCRIBED_BY",
    ),
    "INCLUDES": RelationshipRule(
        ("CatalogItem",),
        ("CatalogItem",),
        "A package includes an item within the same source edition; not an availability assertion.",
        "INCLUDED_IN",
    ),
    "BASELINED_ON": RelationshipRule(
        ("Requirement",),
        ("Signal",),
        "References an evidenced BMW product capability for the proposed change intent.",
        "BASELINE_FOR",
    ),
    "IS_VARIANT_OF": RelationshipRule(
        ("VehicleModel",),
        ("VehicleModel",),
        "Identifies an explicit variant's model generation; does not propagate equipment availability.",
        "HAS_VARIANT",
    ),
}
