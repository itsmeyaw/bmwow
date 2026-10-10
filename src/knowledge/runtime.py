"""Explicit service injection; a missing real database never silently serves synthetic data."""

from bmwow.knowledge import KnowledgeService

_service: KnowledgeService | None = None


def configure_service(service: KnowledgeService | None) -> None:
    global _service
    _service = service


def get_service() -> KnowledgeService:
    if _service is None:
        raise RuntimeError(
            "Knowledge storage is not configured. Inject a KnowledgeService with configure_service(); "
            "the synthetic demonstration is scripts/inspect_knowledge.py."
        )
    return _service
