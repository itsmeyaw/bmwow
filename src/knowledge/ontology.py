"""v1 module compatibility, with implementation under backend/bmwow/knowledge/."""

from bmwow.knowledge import FeedbackFilter

from .runtime import get_service


def list_supported_models():
    return get_service().list_supported_models()


def list_regions():
    return get_service().list_regions()


def get_model(model_code: str):
    return get_service().get_model(model_code)


def list_portfolio(segment: str | None = None, regions: list[str] | None = None):
    return get_service().list_portfolio(segment, regions)


def list_competitor_models(segment: str, regions: list[str], names: list[str] | None = None):
    return get_service().list_competitor_models(segment, regions, names)


def get_attribute_values(model_id: str, attributes: list[str] | None = None):
    return get_service().get_attribute_values(model_id, attributes)


def get_feedback_items(filters: FeedbackFilter):
    return get_service().get_feedback_items(filters)


def get_feedback_page(filters: FeedbackFilter):
    service = get_service()
    method = getattr(service, "get_feedback_page", None)
    return method(filters) if method else None


def get_data_availability():
    service = get_service()
    method = getattr(service, "get_data_availability", None)
    return method() if method else None


def search_documents(
    query: str,
    kinds: list[str] | None = None,
    regions: list[str] | None = None,
    k: int = 10,
):
    return get_service().search_documents(query, kinds, regions, k)


def get_taxonomy():
    return get_service().get_taxonomy()


def get_study_scores(models: list[str], regions: list[str]):
    return get_service().get_study_scores(models, regions)


def resolve_citation(citation_id: str):
    return get_service().resolve_citation(citation_id)
