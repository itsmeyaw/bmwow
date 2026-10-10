"""Explicit service injection; a missing real database never silently serves synthetic data."""

from bmwow.knowledge import FeedbackKnowledgeService, KnowledgeService

ReadService = KnowledgeService | FeedbackKnowledgeService
_service: ReadService | None = None


def configure_service(service: ReadService | None) -> None:
    global _service
    _service = service


def get_service() -> ReadService:
    if _service is None:
        raise RuntimeError(
            "Knowledge storage is not configured. Inject a read service with configure_service(); "
            "the synthetic demonstration is scripts/inspect_knowledge.py."
        )
    return _service
