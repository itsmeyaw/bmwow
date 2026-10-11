"""Replaceable snapshot storage boundary; no database driver or schema assumptions."""

from pathlib import Path
from typing import Protocol

from bmwow.ontology import GraphBundle, validate_bundle


class SnapshotRepository(Protocol):
    def load_snapshot(self) -> GraphBundle: ...


class FileSnapshotRepository:
    """Read a private closed snapshot; source records never belong in tracked fixtures."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load_snapshot(self) -> GraphBundle:
        bundle = GraphBundle.model_validate_json(self.path.read_text(encoding="utf-8"))
        errors = validate_bundle(bundle)
        if errors:
            raise ValueError("Invalid knowledge snapshot:\n" + "\n".join(errors))
        return bundle


class InMemoryRepository:
    """An isolated, validated snapshot for synthetic integration and local development."""

    def __init__(self, bundle: GraphBundle) -> None:
        errors = validate_bundle(bundle)
        if errors:
            raise ValueError("Invalid knowledge snapshot:\n" + "\n".join(errors))
        self._bundle = bundle.model_copy(deep=True)

    def load_snapshot(self) -> GraphBundle:
        return self._bundle.model_copy(deep=True)
