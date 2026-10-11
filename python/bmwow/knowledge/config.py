"""Explicit application curation; unknown model metadata and mappings are not guessed."""

from pydantic import BaseModel, ConfigDict, Field

from .types import MappingStatus
from .types import SearchLocale as LocaleRecord


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchLocale(LocaleRecord, Configuration):
    """Shared locale fields with strict validation at the curation boundary."""


class ModelProfile(Configuration):
    segment: str
    curation_note: str = Field(min_length=1)
    powertrain: str | None = None
    sold_regions: list[str] = Field(default_factory=list)


class VfcMapping(Configuration):
    feature_id: str
    status: MappingStatus
    rationale: str = Field(min_length=1)


class KnowledgeConfig(Configuration):
    model_profiles: dict[str, ModelProfile] = Field(default_factory=dict)
    feature_keys: dict[str, str] = Field(default_factory=dict)
    search_locales: dict[str, SearchLocale] = Field(default_factory=dict)
    vfc_mappings: dict[str, VfcMapping] = Field(default_factory=dict)
    # Exact original labels, reviewed independently of the source's classification.
    study_mappings: dict[str, VfcMapping] = Field(default_factory=dict)
    aspect_mappings: dict[str, VfcMapping] = Field(default_factory=dict)
    # Required for combined-model observations; keys are original Evidence IDs.
    sales_groups: dict[str, str] = Field(default_factory=dict)
    # Explicit opt-in: proposed mappings feed features too (each mention keeps its mapping status).
    # Default False: only reviewed mappings establish feature associations.
    accept_proposed_mappings: bool = False

    def mapped_feature(self, mapping: VfcMapping | None) -> str | None:
        """Feature key a mapping establishes under this curation, else None."""
        if mapping is None or (mapping.status != "reviewed" and not self.accept_proposed_mappings):
            return None
        return self.feature_keys.get(mapping.feature_id)
