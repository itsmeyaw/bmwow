"""structure_agent: one evidence package per feature, judged with a rubric and guarded by code.

1. assemble (code): facts from the four validated reports, per feature (see bmwow/agent/structure.py);
2. judge (LLM): the rubric answers what exactly, how widespread, vs. competitors, regional, trend,
   safety/brand relevance, and an assessment, citing package ids;
3. guard (code): checks the judgment against the package; one revision with the violations, then the
   result is kept and flagged if it still fails.

The judgment reads BMW feedback quotes, so it runs only with ALLOW_LLM_ON_INTERNAL_DATA=true. Code also
computes a rule-based assessment for every feature (structure.rule_assessment): the judge sees it as a
suggestion, and features the judge does not run on keep it (method "rule", low certainty).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import (
    Confidence,
    EvidencePackage,
    FeatureAssessment,
    ProductBrief,
)

from ..config import get_settings
from ..llm import get_chat_model
from ..prompting import render_prompt
from ..rules import Rules, load_rules
from ..structure import guard, render_package, rule_assessment
from ..taxonomy import Taxonomy
from .common import structured_call

log = logging.getLogger(__name__)


class ReasonSentence(BaseModel):
    text: str = Field(description="one sentence of the rubric reasoning")
    cited_ids: list[str] = Field(description="package ids this sentence relies on")


class JudgeOutput(BaseModel):
    assessment: Literal["gap", "strength", "hygiene_factor", "demand", "unclear"]
    what_exactly: str = Field(description="the concrete issue or wish, from sub-themes and quotes")
    widespread: Literal["widespread", "limited", "unclear"]
    certainty: Confidence
    brand_or_safety_relevant: bool
    reasoning: list[ReasonSentence]


def _text(out: JudgeOutput) -> str:
    return " ".join([out.what_exactly, *(s.text for s in out.reasoning)])


def _cited(out: JudgeOutput) -> list[str]:
    return list(dict.fromkeys(cid for s in out.reasoning for cid in s.cited_ids))


async def _ask(
    brief: ProductBrief, taxonomy: Taxonomy, pkg: EvidencePackage, revision: str = ""
) -> JudgeOutput:
    prompt = render_prompt(
        "structure_judge",
        brief=brief,
        taxonomy=taxonomy,
        package=render_package(pkg),
        revision=revision,
    )
    return await structured_call(get_chat_model("strong"), JudgeOutput, prompt)


async def judge_one(
    brief: ProductBrief, taxonomy: Taxonomy, pkg: EvidencePackage, rules: Rules
) -> FeatureAssessment:
    out = await _ask(brief, taxonomy, pkg)
    checks = guard(pkg, out.assessment, out.widespread, _text(out), _cited(out), rules)
    status: Literal["passed", "revised", "flagged"] = "passed"
    if not all(c.ok for c in checks):
        violations = "\n".join(f"- {c.rule}: {c.detail}" for c in checks if not c.ok)
        out = await _ask(
            brief,
            taxonomy,
            pkg,
            revision=f"\n# Guard violations in your previous answer — fix them\n\n{violations}\n",
        )
        checks = guard(pkg, out.assessment, out.widespread, _text(out), _cited(out), rules)
        status = "revised" if all(c.ok for c in checks) else "flagged"
    rule = rule_assessment(pkg, rules)
    return FeatureAssessment(
        attribute=pkg.attribute,
        assessment=out.assessment,
        what_exactly=out.what_exactly,
        widespread=out.widespread,
        certainty=out.certainty,
        brand_or_safety_relevant=out.brand_or_safety_relevant,
        reasoning=" ".join(
            f"{s.text.strip()} [{', '.join(s.cited_ids)}]" if s.cited_ids else s.text.strip()
            for s in out.reasoning
        ),
        cited_ids=_cited(out),
        guard=checks,
        guard_status=status,
        method="judge",
        rule_suggestion=f"{rule.assessment} ({rule.basis})",
    )


def _by_rule(pkg: EvidencePackage, note: str) -> FeatureAssessment:
    """The code's rule-based assessment, used where the judge does not run (low certainty)."""
    r = rule_assessment(pkg, load_rules())
    return FeatureAssessment(
        attribute=pkg.attribute,
        assessment=r.assessment,  # type: ignore[arg-type]
        widespread="unclear",
        certainty="low",
        reasoning=f"{r.reasoning} [{', '.join(r.cited_ids)}]" if r.cited_ids else r.reasoning,
        cited_ids=r.cited_ids,
        note=f"rule-based ({r.basis}); {note}",
        method="rule",
        rule_suggestion=f"{r.assessment} ({r.basis})",
    )


async def judge(
    brief: ProductBrief, taxonomy: Taxonomy, packages: list[EvidencePackage]
) -> list[FeatureAssessment]:
    """Judge the most important features (ranked by assemble); the rest get the rule result."""
    rules = load_rules()
    settings = get_settings()
    top = packages[: rules.structure.max_judged_features]
    rest = [
        _by_rule(p, "outside the most important features judged in this run")
        for p in packages[rules.structure.max_judged_features :]
    ]
    if not settings.allow_llm_on_internal_data:
        note = "judgment needs an LLM on BMW data; disabled until ALLOW_LLM_ON_INTERNAL_DATA=true"
        return [_by_rule(p, note) for p in top] + rest
    semaphore = asyncio.Semaphore(settings.llm_concurrency)

    async def one(pkg: EvidencePackage) -> FeatureAssessment:
        async with semaphore:
            try:
                return await judge_one(brief, taxonomy, pkg, rules)
            except Exception as exc:  # noqa: BLE001 - one feature failing must not stop the rest
                log.exception("judging %s failed", pkg.attribute)
                return _by_rule(pkg, f"judgment failed: {type(exc).__name__}: {exc}")

    return list(await asyncio.gather(*(one(p) for p in top))) + rest
