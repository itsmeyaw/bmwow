"""Typed access to rules.yaml: thresholds, denominators, aliases and budgets used by the nodes."""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Literal

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
    higher_is_better_units: list[str] = Field(default_factory=list)
    lower_is_better_units: list[str] = Field(default_factory=list)
    powertrain_patterns: dict[str, list[str]] = Field(default_factory=dict)
    rule_min_signal: float = 0.01
    rule_min_strength: float = 0.02


class CompetitionRules(_Rules):
    core_features: dict[str, str]
    results_per_query: int
    pages_per_feature: int


class GapFillRules(_Rules):
    max_features: int
    min_customer_ci_low: float


class CandidateRules(_Rules):
    assessments: list[str]
    default_target: dict[str, Literal["competitor_median", "best_in_class", "ours"]]
    max_customer_facts: int
    from_rule_based: bool = False


class Rules(_Rules):
    thin: ThinRules
    feedback: FeedbackRules
    feature_aliases: dict[str, list[str]]
    structure: StructureRules
    competition: CompetitionRules
    gap_fill: GapFillRules
    candidates: CandidateRules


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


class StudyMapping(BaseModel):
    feature: str
    status: str


def load_study_mappings(path: Path) -> dict[str, StudyMapping]:
    """Study question -> feature key from the private curation file (proposed or reviewed); empty
    when the file is missing. The importer only turns reviewed mappings into graph Signals; the agent
    also reads proposed ones and labels them as such."""
    if not path.exists():
        return {}
    knowledge = json.loads(path.read_text(encoding="utf-8")).get("knowledge", {})
    keys = knowledge.get("feature_keys", {})
    return {
        question.strip().lower(): StudyMapping(feature=keys[m["feature_id"]], status=m["status"])
        for question, m in knowledge.get("study_mappings", {}).items()
        if m.get("feature_id") in keys
    }


Powertrain = Literal["bev", "phev", "ice"]


@cache
def _compiled_powertrains() -> list[tuple[str, list[re.Pattern[str]]]]:
    patterns = load_rules().structure.powertrain_patterns
    return [(pt, [re.compile(x, re.IGNORECASE) for x in xs]) for pt, xs in patterns.items()]


def powertrain_of(text: str | None) -> Powertrain | None:
    """bev / phev / ice from a variant or model name, None if no pattern or several match
    (plug-in hybrids are checked before combustion, since '530e' must not read as ICE)."""
    if not text:
        return None
    hits = [pt for pt, patterns in _compiled_powertrains() if any(p.search(text) for p in patterns)]
    if "phev" in hits:
        return "phev"
    return hits[0] if len(hits) == 1 else None  # type: ignore[return-value]


def engine_type(engine_types: list[str]) -> Powertrain | None:
    """The one known engine type an ontology context names, else None."""
    known = {e for e in engine_types if e in ("bev", "phev", "ice")}
    return known.pop() if len(known) == 1 else None  # type: ignore[return-value]


def is_lower_better(attribute: str, unit: str) -> bool:
    s, u = load_rules().structure, unit.strip().lower()
    if u in s.lower_is_better_units:
        return True
    return attribute in s.lower_is_better and u not in s.higher_is_better_units


def is_generic_term(term: str | None) -> bool:
    if not term:
        return True
    text = term.strip().lower()
    return "overall" in text or text in {t.lower() for t in load_rules().feedback.generic_terms}
