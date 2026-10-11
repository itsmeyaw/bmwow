"""Explicit application curation; unknown model metadata and mappings are not guessed."""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from bmwow.ontology.models import Provenance

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
    reviewed_by: str | None = None
    reviewed_at: AwareDatetime | None = None
    review_provenance: Provenance | None = None

    @model_validator(mode="after")
    def consistent_review(self) -> "VfcMapping":
        if self.review_provenance is not None:
            validate_review_provenance(self.review_provenance, self.reviewed_by, self.reviewed_at)
        return self


def validate_review_provenance(
    provenance: Provenance, reviewer: str | None, reviewed_at: AwareDatetime | None
) -> None:
    """Delegation does not change software authorship into human inspection."""
    if provenance.actor_id != reviewer or provenance.created_at != reviewed_at:
        raise ValueError("Review provenance must match the recorded reviewer and time")
    if provenance.actor_type == "software":
        if (
            provenance.method != "llm_extraction"
            or not provenance.model
            or not provenance.prompt_version
        ):
            raise ValueError("Software review requires extraction model and prompt provenance")
    elif provenance.method != "manual_interpretation":
        raise ValueError("Human review requires manual interpretation provenance")


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
