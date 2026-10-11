"""Private, editable curation boundary; no source data is supplied by this module."""

from datetime import date
from pathlib import Path
from typing import Annotated

from pydantic import Field

from bmwow.ontology.models import Feature, GraphBundle, Market, VehicleModel

from .config import Configuration, KnowledgeConfig, ModelProfile, SearchLocale

CuratedNode = Annotated[VehicleModel | Market | Feature, Field(discriminator="type")]


class CurationManifest(Configuration):
    context_nodes: list[CuratedNode]
    knowledge: KnowledgeConfig
    # Source Derivate -> canonical VehicleModel ID; never reconcile by marketing-name similarity.
    feedback_models: dict[str, str] = Field(default_factory=dict)
    # Dataset-specific source markets. EU sales/study coverage is not EU membership.
    source_markets: dict[str, str]
    pending_decisions: list[str] = Field(default_factory=list)

    def seed(self, as_of: date, purpose: str = "production") -> GraphBundle:
        return GraphBundle(
            ontology_version="0.2.0",
            purpose=purpose,
            as_of=as_of,
            description="Curated knowledge snapshot; source scope and unknowns are explicit.",
            nodes=[node.model_copy(deep=True) for node in self.context_nodes],
            edges=[],
        )


def load_manifest(path: Path) -> CurationManifest:
    return CurationManifest.model_validate_json(path.read_text(encoding="utf-8"))


def initial_manifest() -> CurationManifest:
    """Known source codes only. Segment, sale availability, and feature matches need review."""
    models = [
        VehicleModel(
            id=f"vehicle:bmw-{code.lower()}",
            entity_key=f"vehicle:bmw-{code.lower()}",
            label=code,
            revision=1,
            type="VehicleModel",
            properties={
                "brand": "BMW",
                "vehicle_line": code,
                "generation_code": code,
                "model_year": None,
                "variant": None,
                "aliases": [],
            },
        )
        for code in ("F70", "G60", "G68", "G70")
    ]
    markets = []
    source_markets = {}
    for dataset in ("sales", "studies"):
        for code, name, countries in (
            ("EU", "Source-reported Europe", []),
            ("CN", "China", ["CN"]),
            ("US", "United States", ["US"]),
            ("RoW", "Source-reported Rest of World", []),
        ):
            node_id = f"market:{dataset}:{code}"
            source_markets[f"{dataset}:{code}"] = node_id
            markets.append(
                Market(
                    id=node_id,
                    entity_key=node_id,
                    label=f"{name} ({dataset})",
                    revision=1,
                    type="Market",
                    properties={
                        "code": code,
                        "name": name,
                        "country_codes": countries,
                        "definition_notes": [
                            "Original dataset grouping; country coverage is unknown unless explicit.",
                            "Feedback query membership does not establish this dataset's population.",
                        ],
                    },
                )
            )
    note = "TODO(team): review segment, marketing name, powertrain, and sold regions."
    return CurationManifest(
        context_nodes=[*models, *markets],
        knowledge=KnowledgeConfig(
            model_profiles={
                model.id: ModelProfile(segment="unknown", curation_note=note) for model in models
            },
            search_locales={
                "EU": SearchLocale(country="de", lang="en"),
                "CN": SearchLocale(country="cn", lang="en"),
                "US": SearchLocale(country="us", lang="en"),
                # RoW spans countries: a research locale must be explicitly chosen later.
            },
        ),
        feedback_models={model.properties.generation_code: model.id for model in models},
        source_markets=source_markets,
        pending_decisions=[
            note,
            "TODO(team): review canonical Features and exact VFC/study/aspect mappings.",
            "TODO(team): define source EU/RoW populations and RoW research locale.",
            "TODO(team): curate competitors with sources; identify Sources A–D.",
        ],
    )
