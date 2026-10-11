"""Local PDF extraction and explicitly reviewed catalog staging. No provider calls."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field
from pypdf import PdfReader

from bmwow.ontology.models import (
    Capability,
    CatalogItem,
    Context,
    Edge,
    Evidence,
    GraphBundle,
    Provenance,
    Signal,
    SourceDocument,
)

from .config import Configuration, validate_review_provenance
from .ingestion import merge_candidate
from .manifest import CurationManifest


def source_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class CatalogClaim(Configuration):
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    feature_id: str | None = None
    catalog_item_id: str | None = None
    capability: Capability = Field(
        default_factory=lambda: Capability(
            availability="unknown", variant=None, measurement=None, conditions=[], notes=[]
        )
    )
    status: Literal["proposed", "reviewed", "rejected"] = "proposed"
    reviewed_by: str | None = None
    reviewed_at: AwareDatetime | None = None
    visual_checked: bool = False
    scope_checked: bool = False
    conditions_checked: bool = False
    review_note: str | None = None
    review_provenance: Provenance | None = None


class CatalogReview(Configuration):
    source_file: str
    source_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    pages: int = Field(ge=1)
    # File names alone do not establish the model, market, edition, or table column.
    model_id: str | None = None
    country_codes: list[str] = Field(default_factory=list)
    publication_date: str | None = None
    edition_note: str | None = None
    claims: list[CatalogClaim] = Field(default_factory=list)
    catalog_items: list[CatalogItem] = Field(default_factory=list)


def _manual_provenance(claim: CatalogClaim) -> Provenance:
    return Provenance(
        actor_type="human",
        actor_id=claim.reviewed_by,
        method="manual_interpretation",
        created_at=claim.reviewed_at,
        model=None,
        prompt_version=None,
    )


def extract_pages(path: Path) -> list[str]:
    """Text is a locator aid. Table interpretation requires the original visual layout."""
    return [page.extract_text() or "" for page in PdfReader(path).pages]


def prepare_catalog(path: Path, *, theme: str = r"seat|sitz|comfort|komfort") -> CatalogReview:
    pages = extract_pages(path)
    expression = re.compile(theme, re.IGNORECASE)
    claims = [
        CatalogClaim(page=index, quote=line, statement=line)
        for index, text in enumerate(pages, 1)
        for line in text.splitlines()
        if line.strip() and expression.search(line)
    ]
    return CatalogReview(
        source_file=str(path), source_hash=source_hash(path), pages=len(pages), claims=claims
    )


def stage_catalog(
    review: CatalogReview,
    manifest: CurationManifest,
    *,
    as_of: date,
    origin: Literal["provided_bmw", "synthetic"] = "provided_bmw",
) -> GraphBundle:
    """Reject unreviewed/changed evidence; return a closed, fully validated candidate."""
    path = Path(review.source_file)
    if source_hash(path) != review.source_hash:
        raise ValueError("Catalog source changed; prepare and review the new edition")
    pages = extract_pages(path)
    if len(pages) != review.pages:
        raise ValueError("Catalog page count changed")
    claims = [claim for claim in review.claims if claim.status == "reviewed"]
    if not claims:
        raise ValueError("No reviewed catalog claims")
    if not review.model_id or not review.country_codes or not review.edition_note:
        raise ValueError("Review the original model, country scope, and edition note")
    models = {node.id for node in manifest.context_nodes if node.type == "VehicleModel"}
    features = {node.id for node in manifest.context_nodes if node.type == "Feature"}
    if review.model_id not in models:
        raise ValueError("Catalog model is absent from the curated manifest")
    for claim in claims:
        if not (
            claim.reviewed_by
            and claim.reviewed_at
            and claim.review_note
            and claim.visual_checked
            and claim.scope_checked
            and claim.conditions_checked
        ):
            raise ValueError(
                "Reviewed claims require reviewer, time, note, and all three visual checks"
            )
        if claim.feature_id not in features:
            raise ValueError("Review each claim's canonical Feature")
        if claim.review_provenance is not None:
            validate_review_provenance(
                claim.review_provenance, claim.reviewed_by, claim.reviewed_at
            )
        if claim.page > len(pages) or claim.quote not in pages[claim.page - 1]:
            raise ValueError("Catalog quote is not present on the referenced original page")
    bundle = manifest.seed(as_of, "fixture" if origin == "synthetic" else "production")
    source_id = "source:catalog:" + review.source_hash[7:]
    created = datetime.combine(as_of, datetime.min.time(), tzinfo=UTC)
    source = SourceDocument(
        id=source_id,
        entity_key=source_id,
        label=path.name,
        revision=1,
        type="SourceDocument",
        properties=dict(
            source_kind="product_catalog",
            origin=origin,
            location=dict(kind="local_file", path=str(path)),
            publisher=None,
            publication_date=review.publication_date,
            retrieved_at=created,
            content_hash=review.source_hash,
            source_role="primary",
            independence_group=None,
            access="provided_internal",
            quality_notes=[
                review.edition_note,
                "Extracted text is a locator aid; reviewed table/footnote interpretation is recorded per claim.",
            ],
        ),
    )
    bundle.nodes.append(source)
    context = Context(
        vehicle_model_ids=[review.model_id],
        market_ids=[],
        country_codes=review.country_codes,
        engine_types=[],
        as_of=None,
        scope_notes=[
            review.edition_note,
            "Source-country scope is retained; availability in another market is not established.",
        ],
    )
    items = {item.id: item for item in review.catalog_items}
    if len(items) != len(review.catalog_items):
        raise ValueError("CatalogItem identities must be unique")
    if set(items) != {claim.catalog_item_id for claim in claims if claim.catalog_item_id}:
        raise ValueError(
            "Every staged CatalogItem requires an explicitly reviewed describing claim"
        )
    for item in items.values():
        item_scope = item.properties.context.model_dump(exclude={"scope_notes"})
        if item_scope != context.model_dump(exclude={"scope_notes"}) or not any(
            (claim.review_provenance or _manual_provenance(claim)) == item.properties.provenance
            for claim in claims
            if claim.catalog_item_id == item.id
        ):
            raise ValueError(
                "CatalogItems require the describing claim's review provenance and original catalog scope"
            )
        bundle.nodes.append(item.model_copy(deep=True))
    for claim in claims:
        identity = hashlib.sha256(
            (review.source_hash + context.model_dump_json() + claim.model_dump_json()).encode()
        ).hexdigest()
        evidence_id, signal_id = f"evidence:catalog:{identity}", f"signal:catalog:{identity}"
        bundle.nodes.extend(
            [
                Evidence(
                    id=evidence_id,
                    entity_key=evidence_id,
                    label=f"Catalog page {claim.page}",
                    revision=1,
                    type="Evidence",
                    properties=dict(
                        evidence_kind="catalog_excerpt",
                        record_key=f"page:{claim.page}:{identity}",
                        dedup_key=f"{source_id}:{identity}",
                        source_channel=None,
                        locator=dict(kind="pdf", page=claim.page, section=None),
                        raw_text=claim.quote,
                        measurement=None,
                        raw_classifications=[],
                        context=context,
                        limitations=[claim.review_note],
                    ),
                ),
                Signal(
                    id=signal_id,
                    entity_key=signal_id,
                    label=f"Reviewed catalog page {claim.page}",
                    revision=1,
                    type="Signal",
                    properties=dict(
                        signal_kind="product_capability",
                        statement=claim.statement,
                        epistemic_status="publisher_claim",
                        sentiment="not_applicable",
                        context=context,
                        public_context=None,
                        capability=claim.capability,
                        extraction_confidence=dict(level="unassessed", reason=claim.review_note),
                        provenance=claim.review_provenance or _manual_provenance(claim),
                    ),
                ),
            ]
        )
        for relation, start, end in (
            ("IN_SOURCE", evidence_id, source_id),
            ("DERIVED_FROM", signal_id, evidence_id),
            ("CONCERNS", signal_id, claim.feature_id),
        ):
            bundle.edges.append(
                Edge(
                    id=f"edge:catalog:{relation.lower()}:{identity}",
                    type=relation,
                    source_id=start,
                    target_id=end,
                    rationale=claim.review_note,
                    context_transfer=None,
                )
            )
        if claim.catalog_item_id:
            bundle.edges.append(
                Edge(
                    id=f"edge:catalog:item-evidence:{identity}",
                    type="DERIVED_FROM",
                    source_id=claim.catalog_item_id,
                    target_id=evidence_id,
                    rationale=claim.review_note,
                    context_transfer=None,
                )
            )
            bundle.edges.append(
                Edge(
                    id=f"edge:catalog:describes:{identity}",
                    type="DESCRIBES",
                    source_id=signal_id,
                    target_id=claim.catalog_item_id,
                    rationale=claim.review_note,
                    context_transfer=None,
                )
            )
    # The existing merge boundary enforces complete evidence chains and scoped conditions.
    return merge_candidate(manifest.seed(as_of, bundle.purpose), bundle)
