"""Fake chat model and embeddings for offline tests.

`ScriptedChatModel` supports tool binding and structured output (via tool calls), so the real
`create_agent` loops and `with_structured_output` calls run unchanged. `FakeAnalyst` is a rule-based
responder that reads the prompts and tool results the agents produce, the way a cautious model would.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Sequence

import numpy as np
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict

Responder = Callable[[list[BaseMessage], list[str]], AIMessage]

# ---------------------------------------------------------------- embeddings

_STOP = {"the", "a", "an", "is", "are", "and", "or", "in", "on", "to", "of", "for", "my", "this", "it", "at", "as",
         "be", "too", "so", "had", "has", "with", "its", "after", "every", "year", "long", "time", "owner",
         "honestly", "overall", "compared", "old", "car", "daily", "commute", "week", "trips", "city", "six",
         "months", "when", "again", "should", "not", "about", "than", "their", "more"}


class HashEmbeddings(Embeddings):
    """Deterministic bag-of-words hashing embeddings: similar wording → similar vectors."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim)
        for tok in re.findall(r"[a-z]+", text.lower()):
            if tok in _STOP or len(tok) < 3:
                continue
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = np.linalg.norm(v)
        return (v / n if n else v).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


# ---------------------------------------------------------------- chat model


class ScriptedChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    responder: Any
    tool_names: list[str] = []
    calls: list[list[str]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any) -> "ScriptedChatModel":
        names = [convert_to_openai_tool(t)["function"]["name"] for t in tools]
        return self.model_copy(update={"tool_names": names})

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        self.calls.append(self.tool_names)
        msg = self.responder(messages, self.tool_names)
        return ChatResult(generations=[ChatGeneration(message=msg)])


# ---------------------------------------------------------------- rule-based analyst

_ATTR_KEYWORDS = [
    ("real_world_range", ["range"]),
    ("fast_charging", ["charg"]),
    ("seat_ventilation", ["ventilat", "cooled", "cooling", "sweaty"]),
    ("reliable_software", ["software", "infotainment", "laggy", "lag ", "freez", "crash", "slow to respond"]),
    ("rear_space", ["legroom", "rear", "cramped", "back seat", "knee"]),
    ("dynamic_handling", ["handling", "steering", "corners", "dynamics", "chassis", "twisty"]),
    ("physical_controls", ["physical", "buttons"]),
    ("sustainability", ["recycled", "sustainab", "vegan"]),
]
_UNITS = [("km", r"(\d[\d,.]*)\s*km"), ("min", r"(\d[\d,.]*)\s*min"), ("mm", r"(\d[\d,.]*)\s*mm"),
          ("percent", r"(\d[\d,.]*)\s*percent")]
_POSITIVE = ["precise", "fun", "best", "superb", "loves", "sharp", "quickly"]
_DEMAND = ["wish", "need", "should", "please", "expect", "demand", "increasingly"]


def _attribute(text: str) -> str:
    low = text.lower()
    for attr, kws in _ATTR_KEYWORDS:
        if any(k in low for k in kws):
            return attr
    return "unmapped:other"


def _polarity(text: str) -> str:
    low = text.lower()
    if any(w in low for w in _DEMAND):
        return "demand"
    if any(w in low for w in _POSITIVE):
        return "positive"
    return "negative"


def _call(name: str, args: dict[str, Any], i: int = 0) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{name}_{i}"}])


def _system(messages: list[BaseMessage]) -> str:
    return "\n".join(str(m.content) for m in messages if isinstance(m, SystemMessage)) or str(messages[0].content)


def _sentences(text: str) -> list[str]:
    return [s.strip(" #\n") for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip(" #\n")) > 12]


def _web_blocks(messages: list[BaseMessage]) -> list[tuple[str, str]]:
    """(source_id, text) blocks from tool results."""
    out = []
    for m in messages:
        if isinstance(m, ToolMessage):
            for block in re.split(r"\n(?=\[(?:web|kg):)", str(m.content)):
                mm = re.match(r"\[((?:web|kg):[\w-]+)\]", block.strip())
                if mm:
                    out.append((mm.group(1), block))
    return out


def _draft_from_sentence(sid: str, sentence: str, subject: str) -> dict[str, Any]:
    value, unit = None, None
    for u, pat in _UNITS:
        m = re.search(pat, sentence)
        if m and u != "percent":
            value, unit = float(m.group(1).replace(",", "")), u
            break
    qualifier = "WLTP" if "WLTP" in sentence else ("10-80%" if "10-80%" in sentence else "")
    return {"attribute": _attribute(sentence), "claim": f"{subject}: {sentence.rstrip('.')}.",
            "polarity": "neutral", "subject": subject, "value": value, "unit": unit, "qualifier": qualifier,
            "source_ids": [sid], "evidence_quote": sentence, "confidence": "medium"}


class FakeAnalyst:
    """Responds to each prompt type the agents send. Records prompts for assertions."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, messages: list[BaseMessage], tools: list[str]) -> AIMessage:
        prompt = _system(messages) if any(isinstance(m, SystemMessage) for m in messages) else str(messages[-1].content)
        self.prompts.append(prompt)
        if "PositioningOutput" in tools:
            return self._positioning(prompt)
        if "ClusterLabel" in tools:
            return self._label(prompt)
        if "ExplainOutput" in tools:
            return self._explain(prompt)
        if "DraftFindings" in tools:
            return self._competition(messages, prompt)
        if "TrendsOutput" in tools:
            return self._trends(messages, prompt)
        raise AssertionError(f"unexpected tools {tools}")

    def _positioning(self, prompt: str) -> AIMessage:
        keys = re.findall(r"^\[(P\d+)\]\n(.+?) \|", prompt, flags=re.M)
        findings = [{"attribute": "rear_space", "claim": f"{name} overlaps with the planned sedan on segment.",
                     "polarity": "neutral", "subject": name, "source_keys": [key], "confidence": "medium"}
                    for key, name in keys[1:3]]
        return _call("PositioningOutput", {"findings": findings})

    def _label(self, prompt: str) -> AIMessage:
        texts = re.findall(r"^\[T(\d+)\] (.+)$", prompt, flags=re.M)
        joined = " ".join(t for _, t in texts)
        attr = _attribute(joined)
        return _call("ClusterLabel", {
            "attribute": attr, "polarity": _polarity(joined),
            "claim": f"Customers comment on {attr.replace('_', ' ')}.",
            "source_keys": [f"T{i}" for i, _ in texts[:3]], "confidence": "high"})

    def _competition(self, messages: list[BaseMessage], prompt: str) -> AIMessage:
        name = re.search(r"# Competitor\n\n(.+)", prompt)
        subject = name.group(1).strip() if name else "unknown"
        n_tools = sum(isinstance(m, ToolMessage) for m in messages)
        if n_tools == 0:
            return _call("web_search", {"query": f"{subject} specifications"})
        drafts = []
        brand = subject.split(" Sedan")[0].lower()
        for sid, block in _web_blocks(messages):
            if brand not in block.lower():
                continue
            for sentence in _sentences(block.split("\n", 1)[1] if "\n" in block else block):
                if _attribute(sentence) != "unmapped:other":
                    drafts.append(_draft_from_sentence(sid, sentence, subject))
        # One deliberately unsupported number (validator must strip it) and one dangling id.
        if drafts:
            bad = dict(drafts[0], value=999.0, unit="km", claim=f"{subject} has a range of 999 km.")
            drafts.append(bad)
            drafts.append(dict(drafts[0], source_ids=["web:deadbeef"], claim=f"{subject} invented claim."))
        return _call("DraftFindings", {"findings": drafts})

    def _trends(self, messages: list[BaseMessage], prompt: str) -> AIMessage:
        n_tools = sum(isinstance(m, ToolMessage) for m in messages)
        if n_tools == 0:
            return _call("web_search", {"query": "megawatt charging rollout"})
        blocks = re.findall(r"^\[(kg:[\w-]+)\] (.+?)\n(.+?)(?=\n\n\[|\Z)", prompt, flags=re.M | re.S)
        trends = []
        for sid, title, text in blocks:
            sentence = _sentences(text)[0]
            draft = _draft_from_sentence(sid, sentence, "market")
            draft.update(polarity="demand", horizon="1-2y", attribute=_attribute(text))
            trends.append({"name": title.split(":")[-1].split("(")[0].strip(), "category": "technology",
                           "findings": [draft]})
        for sid, block in _web_blocks(messages):
            if sid.startswith("web:"):
                sentence = next(s for s in _sentences(block) if "1,200" in s)
                draft = _draft_from_sentence(sid, sentence, "market")
                draft.update(value=1200.0, unit="charging points", attribute="fast_charging", polarity="demand",
                             horizon="now", evidence_quote=sentence)
                trends.append({"name": "High-power charging rollout", "category": "technology", "findings": [draft]})
                break
        return _call("TrendsOutput", {"trends": trends})

    def _explain(self, prompt: str) -> AIMessage:
        found = re.search(r"^\[(F-[\w-]+)\].*\n  claim: (.+)$", prompt, flags=re.M)
        if not found:
            return _call("ExplainOutput", {"supported": False, "sentences": [], "missing": "relevant findings"})
        fid, claim = found.groups()
        return _call("ExplainOutput", {"supported": True, "missing": "", "sentences": [
            {"text": claim, "cited_ids": [fid]},
            {"text": "This also holds for an unrelated finding.", "cited_ids": ["F-other-999"]},  # must be dropped
            {"text": "It sold 123456789 units.", "cited_ids": [fid]},  # invented number, must be dropped
        ]})


def fake_models() -> tuple[ScriptedChatModel, ScriptedChatModel, HashEmbeddings, FakeAnalyst]:
    analyst = FakeAnalyst()
    return (ScriptedChatModel(responder=analyst), ScriptedChatModel(responder=analyst), HashEmbeddings(), analyst)
