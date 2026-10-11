"""Typed access to rules.yaml: thresholds, denominators, aliases and budgets used by the nodes."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from bmwow.agent.models.evidence import Direction

_YAML = Path(__file__).with_name("rules.yaml")


class _Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ThinRules(_Rules):
    min_n: int
    min_k: int


class Denominator(_Rules):
    label: str
    engine_types: list[str]


class FeedbackRules(_Rules):
    min_k: int
    max_sources_per_finding: int
    max_sub_themes: int
    generic_share_for_llm: float
    llm_sample_size: int
    max_llm_features: int
    candidate_min_k: int
    max_candidates: int
    direction_by_issue_type: dict[str, Direction]
    direction_by_feedback_type: dict[str, Direction]
    generic_terms: list[str]
    denominators: dict[str, Denominator] = Field(default_factory=dict)


class StructureRules(_Rules):
    max_judged_features: int
    max_quotes_per_package: int
    widespread_min_ci_low: float
    thin_words: list[str]
    lower_is_better: list[str]


class CompetitionRules(_Rules):
    core_features: dict[str, str]
    results_per_query: int
    pages_per_feature: int


class GapFillRules(_Rules):
    max_features: int
    min_customer_ci_low: float


class Rules(_Rules):
    thin: ThinRules
    feedback: FeedbackRules
    feature_aliases: dict[str, list[str]]
    structure: StructureRules
    competition: CompetitionRules
    gap_fill: GapFillRules


@cache
def load_rules() -> Rules:
    return Rules.model_validate(yaml.safe_load(_YAML.read_text()))


def _alias_pattern(alias: str) -> re.Pattern[str]:
    alias = alias.strip().lower()
    if alias.endswith("*"):
        return re.compile(r"\b" + re.escape(alias[:-1]))
    return re.compile(r"\b" + re.escape(alias) + r"\b")


@cache
def _compiled_aliases() -> tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]:
    return tuple(
        (feature, tuple(_alias_pattern(a) for a in aliases))
        for feature, aliases in load_rules().feature_aliases.items()
    )


def feature_for_term(term: str | None) -> str | None:
    """The first feature whose alias matches an aspect term (interim mapping, see rules.yaml)."""
    if not term:
        return None
    text = term.lower()
    for feature, patterns in _compiled_aliases():
        if any(p.search(text) for p in patterns):
            return feature
    return None


def is_generic_term(term: str | None) -> bool:
    if not term:
        return True
    text = term.strip().lower()
    return "overall" in text or text in {t.lower() for t in load_rules().feedback.generic_terms}
