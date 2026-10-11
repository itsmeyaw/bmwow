import pytest

from bmwow.knowledge.ingestion import FileCandidateStore, merge_candidate, write_snapshot
from bmwow.knowledge.repository import FileSnapshotRepository
from bmwow.ontology import snapshot_fingerprint


def candidate(bundle):
    source = next(node for node in bundle.nodes if node.type == "SourceDocument").model_copy(
        deep=True
    )
    source.id = source.entity_key = "source:invented-addition"
    result = bundle.model_copy(deep=True)
    result.nodes = [source]
    result.edges = []
    return result


def test_atomic_candidate_acceptance_rejects_stale_writes_and_replays(bundle, tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, bundle)
    store = FileCandidateStore(path)
    old = snapshot_fingerprint(bundle)
    added = candidate(bundle)
    new = store.accept(added, expected_fingerprint=old)
    assert new != old
    after = path.read_bytes()
    with pytest.raises(ValueError, match="Snapshot changed"):
        store.accept(added, expected_fingerprint=old)
    assert path.read_bytes() == after
    assert store.accept(added, expected_fingerprint=new) == new
    assert not path.with_suffix(".json.lock").exists()
    assert len(FileSnapshotRepository(path).load_snapshot().nodes) == len(bundle.nodes) + 1


def test_conflicting_payload_is_not_overwritten(bundle):
    changed = bundle.model_copy(deep=True)
    changed.nodes[0].label = "Invented conflicting interpretation"
    with pytest.raises(ValueError, match="conflicts"):
        merge_candidate(bundle, changed)


def test_invalid_evidence_chain_does_not_change_file(bundle, tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, bundle)
    invalid = bundle.model_copy(deep=True)
    invalid.nodes = [next(node for node in invalid.nodes if node.type == "Evidence")]
    invalid.nodes[0].id = invalid.nodes[0].entity_key = "evidence:invented-dangling"
    invalid.edges = []
    before = path.read_bytes()
    with pytest.raises(ValueError, match="validation"):
        FileCandidateStore(path).accept(invalid, expected_fingerprint=snapshot_fingerprint(bundle))
    assert path.read_bytes() == before


def test_candidate_ingestion_cannot_issue_human_decisions_or_requirements(bundle, tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, bundle)
    with pytest.raises(ValueError, match="separate write paths"):
        FileCandidateStore(path).accept(bundle, expected_fingerprint=snapshot_fingerprint(bundle))


def test_competing_writer_lock_is_preserved(bundle, tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, bundle)
    lock = path.with_suffix(".json.lock")
    lock.write_text("invented other writer")
    with pytest.raises(ValueError, match="Another candidate writer"):
        FileCandidateStore(path).accept(
            candidate(bundle), expected_fingerprint=snapshot_fingerprint(bundle)
        )
    assert lock.exists()


def test_candidate_cannot_change_existing_requirement_or_decision_relationships(bundle, tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, bundle)
    restricted = {node.id for node in bundle.nodes if node.type in {"Requirement", "Decision"}}
    edge = next(
        edge
        for edge in bundle.edges
        if edge.source_id in restricted or edge.target_id in restricted
    ).model_copy(deep=True)
    edge.id = "edge:invented-requirement-change"
    added = candidate(bundle)
    added.nodes = []
    added.edges = [edge]
    before = path.read_bytes()
    with pytest.raises(ValueError, match="relationships use separate"):
        FileCandidateStore(path).accept(added, expected_fingerprint=snapshot_fingerprint(bundle))
    assert path.read_bytes() == before
