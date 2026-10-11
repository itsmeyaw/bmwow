"""Explicit application setup. Missing SQL credentials never activate synthetic feedback."""

from pathlib import Path

from .combined import CombinedKnowledgeService
from .feedback import FeedbackRepository
from .manifest import load_manifest
from .neon import NeonFeedbackConfig, NeonFeedbackRepository
from .repository import FileSnapshotRepository


def create_knowledge_service(
    snapshot_path: Path,
    manifest_path: Path,
    *,
    database_url: str | None = None,
    feedback_repository: FeedbackRepository | None = None,
    neon_config: NeonFeedbackConfig | None = None,
) -> CombinedKnowledgeService:
    manifest = load_manifest(manifest_path)
    if feedback_repository is not None and database_url is not None:
        raise ValueError("Supply either a feedback repository or DATABASE_URL")
    if feedback_repository is None:
        if not database_url:
            raise ValueError(
                "Combined knowledge requires an explicit feedback repository or DATABASE_URL"
            )
        feedback_repository = NeonFeedbackRepository(database_url, neon_config)
    return CombinedKnowledgeService(
        FileSnapshotRepository(snapshot_path),
        manifest.knowledge,
        feedback_repository,
        manifest.feedback_models,
    )
