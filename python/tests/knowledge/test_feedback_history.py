import json

from bmwow.knowledge.feedback import FeedbackKnowledgeService, feedback_id
from bmwow.knowledge.neon import project_feedback
from tests.knowledge.test_neon_feedback import ASPECT_ID, aspect, parent, repository

REVISION = "00000000-0000-5000-8000-000000000099"


def metadata():
    return dict(
        schema_version=1,
        revision_id=REVISION,
        input_hash="sha256:" + "1" * 64,
        text_hash="sha256:" + "2" * 64,
        processing_hash="sha256:" + "3" * 64,
        processing=dict(
            preprocessing="synthetic-v1",
            enrichment_model="none",
            prompt_version="none",
            taxonomy_hash="sha256:" + "4" * 64,
            embedding_model="none",
            embedding_dimensions=0,
        ),
        origins=[
            dict(
                source_file="invented.xlsx",
                source_hash="sha256:" + "5" * 64,
                locator=dict(kind="spreadsheet", sheet="Invented", range="A2:H2"),
            )
        ],
        raw_classifications=[
            dict(
                feedback_type="Defect",
                vfc_level2="Invented screen",
                vfc_level3="Invented freezing label",
                vfc_combined="Original invented combined label",
                locator=dict(kind="spreadsheet", sheet="Invented", range="A2:H2"),
            )
        ],
        original_rows=[{"Customer Feedback": "Original invented text"}],
    )


def test_versioned_projection_pins_original_source_and_full_classification():
    item = project_feedback(parent(provenance=metadata()), [aspect()], "synthetic")
    ref = item.references[0]
    assert item.item_id == feedback_id("synthetic", "synthetic feedback/one")
    assert ref.evidence_id == item.revision_citation == f"feedback_revision:synthetic:{REVISION}"
    assert ref.locator.table == "public.feedback_revisions" and ref.locator.record_key == REVISION
    assert ref.source_version == "sha256:" + "5" * 64
    assert json.loads(ref.locator.original_locator)[0]["locator"]["range"] == "A2:H2"
    assert item.provenance.original_rows == [{"Customer Feedback": "Original invented text"}]
    assert item.classifications[0].vfc_combined == "Original invented combined label"
    assert not any("current import" in note for note in item.limitations)


def test_historical_parent_and_aspect_resolve_after_current_aspects_are_replaced():
    payload = dict(parent=parent(provenance=metadata()), aspects=[aspect()])
    repo, conn, _ = repository([{"relation": "feedback_revisions"}], [{"payload": payload}])
    historical = repo.find_revision(REVISION)
    assert historical.provenance.revision_id == REVISION
    assert conn.calls[-1][1] == (REVISION,)
    repo, conn, _ = repository([], [{"relation": "feedback_revisions"}], [{"payload": payload}])
    old_aspect = repo.find_aspect(str(ASPECT_ID))
    assert old_aspect.references[0].evidence_id.endswith(REVISION)
    assert "@> %s::jsonb" in conn.calls[-1][0]
    assert json.loads(conn.calls[-1][1][0]) == [{"id": str(ASPECT_ID)}]


def test_revision_citations_route_through_feedback_service():
    payload = dict(parent=parent(provenance=metadata()), aspects=[aspect()])
    repo, _, _ = repository([{"relation": "feedback_revisions"}], [{"payload": payload}])
    service = FeedbackKnowledgeService(repo)
    result = service.resolve_citation(f"feedback_revision:bmw-feedback:{REVISION}")
    assert result.provenance.revision_id == REVISION
    assert repo.find_revision("invalid-uuid") is None


def test_legacy_archive_is_pinned_but_does_not_claim_recovered_source_provenance():
    archived = metadata()
    archived.update(origins=[], raw_classifications=[], original_rows=[])
    archived["processing"]["preprocessing"] = (
        "legacy-database-snapshot-v1-original-provenance-unknown"
    )
    archived["processing"]["enrichment_model"] = "unknown"
    item = project_feedback(parent(provenance=archived), [aspect()], "synthetic")
    assert item.revision_citation == f"feedback_revision:synthetic:{REVISION}"
    assert item.references[0].source_version is None
    assert any("source version" in note for note in item.limitations)
    assert any("unlabelled VFC" in note for note in item.limitations)
    assert not any("current import" in note for note in item.limitations)
