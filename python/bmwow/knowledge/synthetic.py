"""Explicit synthetic setup using the existing canonical fixture; never loads raw BMW data."""

from bmwow.ontology import GraphBundle
from bmwow.ontology.models import SourceDocument

from .config import KnowledgeConfig, ModelProfile, SearchLocale
from .repository import InMemoryRepository
from .service import KnowledgeService


def create_synthetic_service(bundle: GraphBundle) -> KnowledgeService:
    sources = [node for node in bundle.nodes if isinstance(node, SourceDocument)]
    if not sources or any(source.properties.origin != "synthetic" for source in sources):
        raise ValueError("The synthetic backend accepts only wholly synthetic source documents")
    note = "Invented application metadata for the integration fixture; no real segment claim."
    profiles = {
        node_id: ModelProfile(segment="synthetic_sedan", curation_note=note, sold_regions=["US"])
        for node_id in (
            "vehicle:bmw-g60",
            "vehicle:bmw-g68",
            "vehicle:bmw-g60-fixture-ev",
            "vehicle:example-sedan",
        )
    }
    config = KnowledgeConfig(
        model_profiles=profiles,
        feature_keys={
            "feature:parking-controls": "parking_control_usability",
            "feature:ac-charging": "ac_charging",
            "feature:electric-range": "electric_range",
        },
        search_locales={"US": SearchLocale(country="us", lang="en")},
        sales_groups={"evidence:fixture-sales": "G60_G68"},
    )
    return KnowledgeService(InMemoryRepository(bundle), config)
