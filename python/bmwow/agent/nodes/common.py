"""Shared node scaffolding: context, failure isolation, LLM output schemas, bounded tool loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import (
    AgentName,
    AgentReport,
    Confidence,
    Finding,
    ProductBrief,
    Quantity,
    Source,
)

from ..config import get_settings
from ..sources import Budget, SourceRegistry
from ..taxonomy import Taxonomy, load_taxonomy
from ..validation import assign_ids, claim_numbers_supported, validate_findings

log = logging.getLogger(__name__)

Polarity = Literal["positive", "negative", "neutral", "demand"]
SUMMARY_MAX_WORDS = 120


# ---------------------------------------------------------------- LLM output schemas
# All fields are required (nullable where optional) so they work with strict provider schemas.
# LLMs never produce Finding ids, Source ids they have not seen, weights or computed numbers.


class DraftFinding(BaseModel):
    attribute: str = Field(description="taxonomy key or unmapped:<snake_case_name>")
    claim: str = Field(description="one sentence, one claim")
    polarity: Polarity
    subject: str
    value: float | None = Field(
        description="number exactly as written in the cited source, else null"
    )
    unit: str | None = Field(
        description="canonical unit, e.g. km, kW, min, EUR, units, share; null if no value"
    )
    qualifier: str = Field(
        description="test cycle / condition / horizon, e.g. WLTP, 10-80%, 2024 DE; empty if none"
    )
    source_ids: list[str] = Field(description="ids shown in tool results, at least one")
    evidence_quote: str = Field(
        description="verbatim passage from the cited source supporting the claim"
    )
    confidence: Confidence


class DraftFindings(BaseModel):
    findings: list[DraftFinding]


# ---------------------------------------------------------------- context


@dataclass
class AgentContext:
    agent: AgentName
    brief: ProductBrief
    taxonomy: Taxonomy
    registry: SourceRegistry = field(default_factory=SourceRegistry)
    budget: Budget = field(default_factory=lambda: Budget(0, 0))
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, float | int] = field(default_factory=dict)
    # id(finding) -> the claim text an LLM wrote; its numbers are checked against the cited excerpts.
    llm_claims: dict[int, str] = field(default_factory=dict)
    # stat name -> source kinds; counts validated findings citing at least one source of those kinds.
    kind_stats: dict[str, set[str]] = field(default_factory=dict)

    def add_source(self, source: Source, full_text: str | None = None) -> Source:
        return self.registry.add(source, full_text)

    def add(self, finding: Finding | None, *, llm_claim: str | None = None) -> None:
        if finding is not None:
            self.findings.append(finding)
            if llm_claim is not None:
                self.llm_claims[id(finding)] = llm_claim

    def add_draft(self, draft: DraftFinding, **kwargs: Any) -> Finding:
        finding = self.from_draft(draft, **kwargs)
        self.add(finding, llm_claim=draft.claim)
        return finding

    def finding(
        self,
        *,
        attribute: str,
        claim: str,
        polarity: Polarity,
        subject: str,
        source_ids: list[str],
        confidence: Confidence,
        quantity: Quantity | None = None,
        weight: float = 1.0,
    ) -> Finding:
        """A finding without its final id (ids are assigned after validation)."""
        return Finding(
            id="",
            agent=self.agent,
            attribute=self.taxonomy.normalize(attribute),
            claim=claim.strip(),
            polarity=polarity,
            subject=subject,
            quantity=quantity,
            source_ids=source_ids,
            confidence=confidence,
            weight=weight,
        )

    def from_draft(
        self,
        draft: DraftFinding,
        *,
        subject: str | None = None,
        claim_suffix: str = "",
        qualifier_suffix: str = "",
    ) -> Finding:
        """Map an LLM draft to a Finding. Quotes are verified against the cited sources' full text and
        become the excerpt; the validator then checks ids and numbers."""
        for sid in draft.source_ids:
            self.registry.attach_quote(sid, draft.evidence_quote)
        quantity = None
        if draft.value is not None and draft.unit:
            qualifier = " ".join(x for x in (draft.qualifier.strip(), qualifier_suffix) if x)
            quantity = Quantity(
                value=draft.value,
                unit=draft.unit.strip(),
                qualifier=qualifier,
                origin="source_text",
            )
        claim = draft.claim.strip()
        if claim_suffix:
            claim = f"{claim.rstrip('.')} {claim_suffix}."
        return self.finding(
            attribute=draft.attribute,
            claim=claim,
            polarity=draft.polarity,
            subject=subject or draft.subject,
            source_ids=list(dict.fromkeys(draft.source_ids)),
            confidence=draft.confidence,
            quantity=quantity,
        )

    def build_report(self, crashed: bool = False) -> AgentReport:
        sources = self.registry.sources()
        by_id = {s.id: s for s in sources}
        findings = [
            f
            for f in self.findings
            if id(f) not in self.llm_claims
            or claim_numbers_supported(
                self.llm_claims[id(f)], [by_id[sid] for sid in f.source_ids if sid in by_id]
            )
        ]
        n_unsupported = len(self.findings) - len(findings)
        kept, dropped, dropped_q = validate_findings(findings, sources)
        dropped += n_unsupported
        kept = assign_ids(self.agent, kept)
        cited = {sid for f in kept for sid in f.source_ids}
        kinds = {s.id: s.kind for s in sources}
        for name, wanted in self.kind_stats.items():
            self.stats[name] = sum(
                1 for f in kept if any(kinds.get(sid) in wanted for sid in f.source_ids)
            )
        stats = {
            **self.stats,
            "dropped_findings": dropped,
            "dropped_quantities": dropped_q,
            "dropped_unsupported_numbers": n_unsupported,
            "n_findings": len(kept),
            "n_sources": len(cited),
        }
        if not self.errors and not crashed:
            status = "ok"
        else:
            status = "partial" if kept else "failed"
        return AgentReport(
            agent=self.agent,
            status=status,
            findings=kept,
            sources=[s for s in sources if s.id in cited],
            summary=summarize(self.agent, kept, stats, self.errors),
            stats=stats,
            errors=self.errors,
        )


def summarize(
    agent: AgentName, findings: list[Finding], stats: dict[str, Any], errors: list[str]
) -> str:
    """Deterministic UI summary (<= 120 words) built from the validated findings."""
    if not findings:
        text = f"No validated {agent} findings." + (
            f" {len(errors)} error(s); see errors." if errors else ""
        )
        return text
    top = sorted(
        findings, key=lambda f: (-f.weight, {"high": 0, "medium": 1, "low": 2}[f.confidence])
    )[:3]
    head = f"{len(findings)} {agent} findings from {stats.get('n_sources', 0)} sources."
    text = head + " Key: " + " ".join(f.claim for f in top)
    if errors:
        text += f" ({len(errors)} error(s).)"
    words = text.split()
    return (
        text if len(words) <= SUMMARY_MAX_WORDS else " ".join(words[: SUMMARY_MAX_WORDS - 1]) + " …"
    )


# ---------------------------------------------------------------- isolation

AgentRun = Callable[[AgentContext], Awaitable[None]]


def agent_node(
    agent: AgentName, run: AgentRun
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """Wrap an agent so exceptions and timeouts never stop the run (SPEC §6.0.5).

    Whatever the agent added to its context before failing is still validated and reported as
    `partial`; with nothing usable the status is `failed`.
    """

    async def node(state: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        brief: ProductBrief = state["brief"]
        crashed = False
        ctx: AgentContext | None = None
        try:
            ctx = AgentContext(
                agent=agent,
                brief=brief,
                taxonomy=await load_taxonomy(),
                budget=Budget(
                    settings.max_tool_calls_per_agent, settings.max_pages_scraped_per_agent
                ),
            )
            await asyncio.wait_for(run(ctx), timeout=settings.agent_timeout_s)
        except TimeoutError:
            crashed = True
            if ctx is not None:
                ctx.errors.append(f"timeout after {settings.agent_timeout_s}s")
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            crashed = True
            log.exception("%s agent failed", agent)
            if ctx is not None:
                ctx.errors.append(f"{type(exc).__name__}: {exc}")
            else:
                return {
                    "reports": {
                        agent: AgentReport(
                            agent=agent,
                            status="failed",
                            findings=[],
                            sources=[],
                            summary=f"{agent} agent failed before starting.",
                            errors=[f"{type(exc).__name__}: {exc}"],
                        )
                    }
                }
        assert ctx is not None
        return {"reports": {agent: ctx.build_report(crashed=crashed)}}

    node.__name__ = f"{agent}_agent"
    return node


# ---------------------------------------------------------------- LLM helpers


async def structured_call[S: BaseModel](model: BaseChatModel, schema: type[S], prompt: str) -> S:
    """One structured LLM call (no tools)."""
    result = await model.with_structured_output(schema).ainvoke([HumanMessage(prompt)])
    if isinstance(result, dict):
        result = schema.model_validate(result)
    return result  # type: ignore[return-value]


async def run_tool_loop[S: BaseModel](
    model: BaseChatModel,
    tools: list[BaseTool],
    prompt: str,
    schema: type[S],
    max_tool_calls: int,
    task: str = "Start now.",
) -> S | None:
    """Bounded agent loop (`create_agent` + `response_format`). Tool budgets are enforced inside the
    tools; the recursion limit is a hard backstop."""
    agent = create_agent(
        model, tools, system_prompt=prompt, response_format=schema, checkpointer=False
    )
    result = await agent.ainvoke(
        {"messages": [HumanMessage(task)]},
        config={"recursion_limit": 2 * max_tool_calls + 8},
    )
    out = result.get("structured_response")
    if isinstance(out, dict):
        out = schema.model_validate(out)
    return out
