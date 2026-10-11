"""candidate_agent: requirement candidates from judged features (see bmwow/agent/candidates.py).

Code builds each candidate (intent, baseline, target options, default target, customer facts,
evidence). If BMW data may go to an LLM, the LLM rewords the statement; the wording guard checks that it
states the target, is quantitative and uses only numbers from the facts. One revision, otherwise the
quantitative template wording stays.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import EvidencePackage, ProductBrief, RequirementCandidate

from ..candidates import facts_text, wording_guard
from ..config import get_settings
from ..llm import get_chat_model
from ..prompting import render_prompt
from ..structure import render_package
from ..taxonomy import Taxonomy
from .common import structured_call

log = logging.getLogger(__name__)


class CandidateWording(BaseModel):
    statement: str = Field(description="quantitative: states the target exactly as given")
    customer_value: str = Field(description="one sentence, from the customer facts")


async def _ask(
    brief: ProductBrief, taxonomy: Taxonomy, c: RequirementCandidate, pkg_text: str, revision: str
) -> CandidateWording:
    rule = f" ({c.target.rule})" if c.target else ""
    prompt = render_prompt(
        "candidate_statement",
        brief=brief,
        taxonomy=taxonomy,
        facts=facts_text(c),
        draft=c.statement,
        target_rule=rule
        if c.target
        else "; there is no target, so quantify with the customer facts",
        intent=c.change_intent,
        revision=revision,
        package=pkg_text,
    )
    return await structured_call(get_chat_model("strong"), CandidateWording, prompt)


async def word(
    brief: ProductBrief, taxonomy: Taxonomy, c: RequirementCandidate, pkg: EvidencePackage | None
) -> RequirementCandidate:
    """LLM wording if allowed and guarded; the template wording otherwise."""
    if not get_settings().allow_llm_on_internal_data or pkg is None:
        return c
    pkg_text = render_package(pkg)
    try:
        out = await _ask(brief, taxonomy, c, pkg_text, "")
        checks = wording_guard(c, out.statement, out.customer_value, pkg_text)
        if not all(k.ok for k in checks):
            violations = "\n".join(f"- {k.rule}: {k.detail}" for k in checks if not k.ok)
            out = await _ask(
                brief,
                taxonomy,
                c,
                pkg_text,
                f"\n# Guard violations in your previous answer — fix them\n\n{violations}\n",
            )
            checks = wording_guard(c, out.statement, out.customer_value, pkg_text)
    except Exception as exc:  # noqa: BLE001 - the template wording stands on its own
        log.exception("wording %s failed", c.id)
        return c.model_copy(update={"open_points": [*c.open_points, f"wording failed: {exc}"]})
    if all(k.ok for k in checks):
        return c.model_copy(
            update={
                "statement": out.statement.strip(),
                "customer_value": out.customer_value.strip(),
                "wording": "llm",
                "guard": checks,
            }
        )
    return c.model_copy(update={"guard": checks})  # template wording kept, violations recorded


async def word_all(
    brief: ProductBrief,
    taxonomy: Taxonomy,
    candidates: list[RequirementCandidate],
    packages: list[EvidencePackage],
) -> list[RequirementCandidate]:
    by_attr = {p.attribute: p for p in packages}
    semaphore = asyncio.Semaphore(get_settings().llm_concurrency)

    async def one(c: RequirementCandidate) -> RequirementCandidate:
        async with semaphore:
            return await word(brief, taxonomy, c, by_attr.get(c.attribute))

    return list(await asyncio.gather(*(one(c) for c in candidates)))
