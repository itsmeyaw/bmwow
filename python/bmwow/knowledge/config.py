"""Explicit application curation; unknown model metadata and mappings are not guessed."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchLocale(Configuration):
    country: str
    lang: str


class ModelProfile(Configuration):
    segment: str
    curation_note: str = Field(min_length=1)
    powertrain: str | None = None
    sold_regions: list[str] = Field(default_factory=list)


class VfcMapping(Configuration):
    feature_id: str
    status: Literal["proposed", "reviewed"]
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
