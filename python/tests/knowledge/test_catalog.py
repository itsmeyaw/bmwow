from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from bmwow.knowledge.catalog import prepare_catalog, stage_catalog
from bmwow.knowledge.ingestion import FileCandidateStore, write_snapshot
from bmwow.knowledge.manifest import initial_manifest
from bmwow.knowledge.repository import InMemoryRepository
from bmwow.knowledge.service import KnowledgeService
from bmwow.ontology import snapshot_fingerprint, validate_bundle
from bmwow.ontology.models import CatalogItem, Feature

AS_OF = date(2026, 10, 11)


def synthetic_pdf(path):
    writer = PdfWriter()
    for text in ("Invented seat comfort option", "Invented unrelated section"):
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(path)


@pytest.fixture
def review(tmp_path):
    path = tmp_path / "synthetic-catalog.pdf"
    synthetic_pdf(path)
    return prepare_catalog(path)


def make_manifest():
    result = initial_manifest()
    result.context_nodes.append(
        Feature(
            id="feature:invented-seat",
            entity_key="feature:invented-seat",
            label="Invented seat",
            revision=1,
            type="Feature",
            properties=dict(definition="Invented seat comfort", domains=["interior"], aliases=[]),
        )
    )
    result.knowledge.feature_keys["feature:invented-seat"] = "invented_seat"
    return result


@pytest.fixture
def manifest():
    return make_manifest()


def reviewed(review):
    review.model_id = "vehicle:bmw-g70"
    review.country_codes = ["DE"]
    review.edition_note = "Synthetic German edition; US availability is unknown."
    claim = review.claims[0]
    claim.feature_id = "feature:invented-seat"
    claim.status = "reviewed"
    claim.reviewed_by = "synthetic-reviewer"
    claim.reviewed_at = datetime(2026, 10, 11, tzinfo=UTC)
    claim.review_note = "Synthetic table columns, original scope, and footnotes checked."
    claim.visual_checked = claim.scope_checked = claim.conditions_checked = True
    claim.capability.availability = "optional"
    return review


def test_extraction_never_accepts_a_claim_automatically(review, manifest):
    assert review.pages == 2 and len(review.claims) == 1
    assert review.model_id is None and review.country_codes == []
    assert review.claims[0].capability.availability == "unknown"
    with pytest.raises(ValueError, match="No reviewed"):
        stage_catalog(review, manifest, as_of=AS_OF, origin="synthetic")


@pytest.mark.parametrize("field", ["visual_checked", "scope_checked", "conditions_checked"])
def test_acceptance_requires_each_visual_review_check(review, manifest, field):
    reviewed(review)
    setattr(review.claims[0], field, False)
    with pytest.raises(ValueError, match="all three"):
        stage_catalog(review, manifest, as_of=AS_OF, origin="synthetic")


def test_acceptance_rejects_fabricated_quote_and_changed_source(review, manifest):
    reviewed(review)
    review.claims[0].quote = "Invented fabricated quotation"
    with pytest.raises(ValueError, match="quote"):
        stage_catalog(review, manifest, as_of=AS_OF, origin="synthetic")
    path = Path(review.source_file)
    path.write_bytes(path.read_bytes() + b"\n% changed source")
    with pytest.raises(ValueError, match="changed"):
        stage_catalog(review, manifest, as_of=AS_OF, origin="synthetic")


def test_reviewed_candidate_validates_and_accepts_atomically_without_widening_scope(
    review, manifest, tmp_path
):
    bundle = stage_catalog(reviewed(review), manifest, as_of=AS_OF, origin="synthetic")
    assert validate_bundle(bundle) == []
    service = KnowledgeService(InMemoryRepository(bundle), manifest.knowledge)
    capability = service.get_attribute_values("G70")[0]
    assert capability.availability == "optional" and capability.context.country_codes == ["DE"]
    assert "US" not in capability.context.country_codes
    assert capability.references[0].locator.page == 1
    path = tmp_path / "accepted.json"
    base = manifest.seed(AS_OF, "fixture")
    write_snapshot(path, base)
    store = FileCandidateStore(path)
    accepted = store.accept(bundle, expected_fingerprint=snapshot_fingerprint(base))
    assert store.accept(bundle, expected_fingerprint=accepted) == accepted
    with pytest.raises(ValueError, match="changed"):
        store.accept(bundle, expected_fingerprint=snapshot_fingerprint(base))


def test_catalog_items_require_reviewed_describing_claim_and_original_scope(review, manifest):
    reviewed(review)
    bundle = stage_catalog(review, manifest, as_of=AS_OF, origin="synthetic")
    signal = next(node for node in bundle.nodes if node.type == "Signal")
    item = CatalogItem(
        id="catalog:synthetic-seat",
        entity_key="catalog:synthetic-seat",
        label="Invented equipment",
        revision=1,
        type="CatalogItem",
        properties=dict(
            item_kind="equipment",
            equipment_code="INVENTED",
            description="Invented seat equipment",
            context=signal.properties.context,
            conditions=[],
            notes=[],
            provenance=signal.properties.provenance,
        ),
    )
    review.catalog_items.append(item)
    with pytest.raises(ValueError, match="describing claim"):
        stage_catalog(review, manifest, as_of=AS_OF, origin="synthetic")
    review.claims[0].catalog_item_id = item.id
    staged = stage_catalog(review, manifest, as_of=AS_OF, origin="synthetic")
    assert not validate_bundle(staged)
    assert any(edge.type == "DESCRIBES" and edge.target_id == item.id for edge in staged.edges)
    item.properties.context = item.properties.context.model_copy(update={"country_codes": ["US"]})
    with pytest.raises(ValueError, match="original catalog scope"):
        stage_catalog(review, manifest, as_of=AS_OF, origin="synthetic")
