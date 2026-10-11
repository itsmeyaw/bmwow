"""Validated candidate merging and atomic local writes, separate from the read service."""

import os
import tempfile
from pathlib import Path

from bmwow.ontology import GraphBundle, snapshot_fingerprint, validate_bundle

from .repository import FileSnapshotRepository


def merge_candidate(base: GraphBundle, candidate: GraphBundle) -> GraphBundle:
    """Identical identities are idempotent; conflicting payloads require explicit revisions."""
    if base.ontology_version != candidate.ontology_version or base.purpose != candidate.purpose:
        raise ValueError("Candidate version and purpose must match the snapshot")
    nodes = {node.id: node.model_copy(deep=True) for node in base.nodes}
    edges = {edge.id: edge.model_copy(deep=True) for edge in base.edges}
    for incoming, existing in ((candidate.nodes, nodes), (candidate.edges, edges)):
        for value in incoming:
            if value.id in existing and value != existing[value.id]:
                raise ValueError("Candidate conflicts with an existing identity; create a revision")
            existing[value.id] = value.model_copy(deep=True)
    result = base.model_copy(deep=True)
    result.as_of = max(base.as_of, candidate.as_of)
    result.nodes = [nodes[key] for key in sorted(nodes)]
    result.edges = [edges[key] for key in sorted(edges)]
    errors = validate_bundle(result)
    if errors:
        # Keep record content out of import logs. The caller can inspect its private candidate.
        raise ValueError(f"Merged candidate failed graph validation ({len(errors)} errors)")
    return result


def write_snapshot(path: Path, bundle: GraphBundle) -> None:
    errors = validate_bundle(bundle)
    if errors:
        raise ValueError(f"Snapshot failed graph validation ({len(errors)} errors)")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".snapshot-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(bundle.model_dump_json(indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class FileCandidateStore:
    """Single-writer local acceptance with a stale-snapshot check; no human Decision writes."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def accept(self, candidate: GraphBundle, *, expected_fingerprint: str) -> str:
        if any(node.type in {"Requirement", "Decision"} for node in candidate.nodes):
            raise ValueError("Requirement proposals and human Decisions use separate write paths")
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError("Another candidate writer holds this snapshot lock") from None
        try:
            os.close(fd)
            base = FileSnapshotRepository(self.path).load_snapshot()
            restricted = {
                node.id for node in base.nodes if node.type in {"Requirement", "Decision"}
            }
            if any(
                edge.source_id in restricted or edge.target_id in restricted
                for edge in candidate.edges
            ):
                raise ValueError("Requirement and Decision relationships use separate write paths")
            if snapshot_fingerprint(base) != expected_fingerprint:
                raise ValueError(
                    "Snapshot changed; revalidate the candidate against the current version"
                )
            merged = merge_candidate(base, candidate)
            write_snapshot(self.path, merged)
            return snapshot_fingerprint(merged)
        finally:
            lock_path.unlink()
