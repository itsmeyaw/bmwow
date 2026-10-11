"""Answers to a PM's question, only from given evidence, citing finding/source ids in every sentence.

Shared by `service.explain` (a finished run) and the PM gate ("why?" on a requirement candidate). The
answer is written by an LLM and checked by code: only allowed ids, no numbers outside the evidence. The
evidence includes BMW feedback text, so the LLM runs only with ALLOW_LLM_ON_INTERNAL_DATA=true; otherwise
the evidence itself is returned.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import Finding, ProductBrief, Source

from .config import get_settings
from .llm import get_chat_model, get_embeddings
from .prompting import render_prompt
from .taxonomy import load_taxonomy
from .validation import sentence_supported

EXPLAIN_TOP_K = 8


class Explanation(BaseModel):
    answer: str
    cited_ids: list[str] = Field(default_factory=list)


class ExplainSentence(BaseModel):
    text: str
    cited_ids: list[str] = Field(
        description="finding ids (F-...) and/or source ids from the evidence"
    )


class ExplainOutput(BaseModel):
    supported: bool
    sentences: list[ExplainSentence]
    missing: str = Field(description="what evidence is missing; empty if supported")


def _render_finding(f: Finding) -> str:
    q = ""
    if f.quantity:
        value = (
            f"{f.quantity.value:.1%}"
            if f.quantity.unit == "share"
            else f"{f.quantity.value:g} {f.quantity.unit}"
        )
        q = f" | quantity: {value} {f.quantity.qualifier}".rstrip()
    w = f" | weight: {f.weight:.1%}" if f.weight != 1.0 else ""
    return (
        f"[{f.id}] agent={f.agent} attribute={f.attribute} subject={f.subject} polarity={f.polarity} "
        f"confidence={f.confidence}{q}{w} sources={', '.join(f.source_ids)}\n  claim: {f.claim}"
    )


async def retrieve(question: str, findings: list[Finding], k: int) -> list[Finding]:
    if len(findings) <= k:
        return findings
    emb = get_embeddings()
    texts = [f"{f.attribute} {f.subject}: {f.claim}" for f in findings]
    vecs = np.asarray(await emb.aembed_documents(texts), dtype=float)
    q = np.asarray(await emb.aembed_query(question), dtype=float)
    vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)
    q /= max(float(np.linalg.norm(q)), 1e-12)
    order = np.argsort(-(vecs @ q), kind="stable")[:k]
    return [findings[int(i)] for i in order]


def _context(targets: list[Finding], sources: dict[str, Source]) -> tuple[str, set[str]]:
    cited = [sources[sid] for f in targets for sid in f.source_ids if sid in sources]
    cited = list({s.id: s for s in cited}.values())
    context = (
        "\n".join(_render_finding(f) for f in targets)
        + "\n\nSources:\n"
        + "\n".join(f"[{s.id}] ({s.kind}) {s.title}\n  excerpt: {s.excerpt}" for s in cited)
    )
    return context, {f.id for f in targets} | {s.id for s in cited}


async def answer_from_evidence(
    brief: ProductBrief, targets: list[Finding], sources: dict[str, Source], question: str
) -> Explanation:
    if not targets:
        return Explanation(
            answer="The stored analysis has no findings to answer from.", cited_ids=[]
        )
    context, allowed = _context(targets, sources)
    if not get_settings().allow_llm_on_internal_data:
        listing = "; ".join(f"[{f.id}] {f.claim}" for f in targets)
        return Explanation(
            answer="An LLM answer needs ALLOW_LLM_ON_INTERNAL_DATA=true. The evidence: " + listing,
            cited_ids=[f.id for f in targets],
        )
    prompt = render_prompt(
        "explain_answer",
        brief=brief,
        taxonomy=await load_taxonomy(),
        question=question,
        context=context,
    )
    out = await get_chat_model("strong").with_structured_output(ExplainOutput).ainvoke(prompt)
    if isinstance(out, dict):
        out = ExplainOutput.model_validate(out)
    kept = [s for s in out.sentences if sentence_supported(s.text, s.cited_ids, allowed, context)]
    if not out.supported or not kept:
        missing = out.missing.strip() or "evidence that directly addresses the question"
        return Explanation(
            answer=f"The stored evidence does not support an answer. Missing: {missing}",
            cited_ids=[],
        )
    answer = " ".join(f"{s.text.strip()} [{', '.join(s.cited_ids)}]" for s in kept)
    cited = list(dict.fromkeys(cid for s in kept for cid in s.cited_ids))
    return Explanation(answer=answer, cited_ids=cited)
