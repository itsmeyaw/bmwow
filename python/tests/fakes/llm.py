"""Fake chat model and embeddings for offline tests.

`ScriptedChatModel` supports tool binding and structured output (via tool calls), so the real
`create_agent` loops and `with_structured_output` calls run unchanged. `FakeAnalyst` is a rule-based
responder that reads the prompts and tool results the agents produce, the way a cautious model would.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict

Responder = Callable[[list[BaseMessage], list[str]], AIMessage]

# ---------------------------------------------------------------- embeddings

_STOP = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "and",
    "or",
    "in",
    "on",
    "to",
    "of",
    "for",
    "my",
    "this",
    "it",
    "at",
    "as",
    "be",
    "too",
    "so",
    "had",
    "has",
    "with",
    "its",
    "after",
    "every",
    "year",
    "long",
    "time",
    "owner",
    "honestly",
    "overall",
    "compared",
    "old",
    "car",
    "daily",
    "commute",
    "week",
    "trips",
    "city",
    "six",
    "months",
    "when",
    "again",
    "should",
    "not",
    "about",
    "than",
    "their",
    "more",
}


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

    def bind_tools(
        self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any
    ) -> ScriptedChatModel:
        names = [convert_to_openai_tool(t)["function"]["name"] for t in tools]
        return self.model_copy(update={"tool_names": names})

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self.calls.append(self.tool_names)
        msg = self.responder(messages, self.tool_names)
        return ChatResult(generations=[ChatGeneration(message=msg)])


# ---------------------------------------------------------------- rule-based analyst

_ATTR_KEYWORDS = [
    ("real_world_range", ["range"]),
    ("fast_charging", ["charg"]),
    ("seat_ventilation", ["ventilat", "cooled", "cooling", "sweaty"]),
    (
        "reliable_software",
        ["software", "infotainment", "laggy", "lag ", "freez", "crash", "slow to respond"],
    ),
    ("rear_space", ["legroom", "rear", "cramped", "back seat", "knee"]),
    ("dynamic_handling", ["handling", "steering", "corners", "dynamics", "chassis", "twisty"]),
    ("physical_controls", ["physical", "buttons"]),
    ("sustainability", ["recycled", "sustainab", "vegan"]),
]
_UNITS = [
    ("km", r"(\d[\d,.]*)\s*km"),
    ("min", r"(\d[\d,.]*)\s*min"),
    ("mm", r"(\d[\d,.]*)\s*mm"),
    ("percent", r"(\d[\d,.]*)\s*percent"),
]


def _attribute(text: str) -> str:
    low = text.lower()
    for attr, kws in _ATTR_KEYWORDS:
        if any(k in low for k in kws):
            return attr
    return "unmapped:other"


def _call(name: str, args: dict[str, Any], i: int = 0) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": f"call_{name}_{i}"}]
    )


def _system(messages: list[BaseMessage]) -> str:
    return "\n".join(str(m.content) for m in messages if isinstance(m, SystemMessage)) or str(
        messages[0].content
    )


def _sentences(text: str) -> list[str]:
    return [
        s.strip(" #\n") for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip(" #\n")) > 12
    ]


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
    return {
        "attribute": _attribute(sentence),
        "claim": f"{subject}: {sentence.rstrip('.')}.",
        "polarity": "neutral",
        "subject": subject,
        "value": value,
        "unit": unit,
        "qualifier": qualifier,
        "source_ids": [sid],
        "evidence_quote": sentence,
        "confidence": "medium",
    }


class FakeAnalyst:
    """Responds to each prompt type the agents send. Records prompts for assertions."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, messages: list[BaseMessage], tools: list[str]) -> AIMessage:
        prompt = (
            _system(messages)
            if any(isinstance(m, SystemMessage) for m in messages)
            else str(messages[-1].content)
        )
        self.prompts.append(prompt)
        if "PositioningOutput" in tools:
            return self._positioning(prompt)
        if "SubThemeOutput" in tools:
            return self._sub_themes(prompt)
        if "JudgeOutput" in tools:
            return self._judge(prompt)
        if "ExtractionOutput" in tools:
            return self._extract(prompt)
        if "CandidateWording" in tools:
            return self._wording(prompt)
        if "ParsedConstraints" in tools:
            return self._constraints(prompt)
        if "ExplainOutput" in tools:
            return self._explain(prompt)
        if "DraftFindings" in tools:
            return self._competition(messages, prompt)
        if "TrendsOutput" in tools:
            return self._trends(messages, prompt)
        raise AssertionError(f"unexpected tools {tools}")

    def _positioning(self, prompt: str) -> AIMessage:
        keys = re.findall(r"^\[(P\d+)\]\n(.+?) \|", prompt, flags=re.M)
        findings = [
            {
                "attribute": "rear_space",
                "claim": f"{name} overlaps with the planned sedan on segment.",
                "polarity": "neutral",
                "subject": name,
                "source_keys": [key],
                "confidence": "medium",
            }
            for key, name in keys[1:3]
        ]
        return _call("PositioningOutput", {"findings": findings})

    def _wording(self, prompt: str) -> AIMessage:
        """First answer omits the target and invents a number; the revision states the target."""
        facts = prompt.split("# Candidate facts", 1)[1].split("Draft wording", 1)[0]
        target = re.search(r"^target (\S+) (\S+) (\S+)$", facts, flags=re.M)
        fact = next((ln for ln in facts.splitlines() if "% of feedback items" in ln), "")
        if "Guard violations" not in prompt:
            return _call(
                "CandidateWording",
                {
                    "statement": "The successor should be much better, like 42 times better.",
                    "customer_value": "Customers care.",
                },
            )
        if target:
            op, value, unit = target.groups()
            statement = f"The successor should reach {op} {value} {unit}, matching the evidence."
        else:
            statement = f"The successor should address this: {fact}."
        return _call(
            "CandidateWording",
            {
                "statement": statement,
                "customer_value": fact or "Customers raise it.",
            },
        )

    def _constraints(self, prompt: str) -> AIMessage:
        """Reads 'freeze REQ-n', 'cap REQ-n 520', 'REQ-n not important'; plants a value the PM did not
        write and an unknown candidate, both of which code must drop."""
        text = prompt.split("# PM instruction (verbatim)", 1)[1].split("# Task", 1)[0].lower()
        out = []
        for cid, rest in re.findall(r"(req-\d+)([^;]*)", text):
            cid = cid.upper()
            number = re.search(r"(\d+(?:\.\d+)?)", rest)
            if "freeze" in rest or "don't change" in rest or "do not change" in rest:
                out.append(
                    {"candidate_id": cid, "kind": "freeze", "value": None, "reason": rest.strip()}
                )
            elif "not important" in rest:
                out.append(
                    {
                        "candidate_id": cid,
                        "kind": "deprioritize",
                        "value": None,
                        "reason": rest.strip(),
                    }
                )
            elif ("max" in rest or "up to" in rest) and number:
                out.append(
                    {
                        "candidate_id": cid,
                        "kind": "cap",
                        "value": float(number.group(1)),
                        "reason": "",
                    }
                )
        out.append({"candidate_id": "REQ-1", "kind": "set", "value": 12345.0, "reason": "planted"})
        out.append(
            {"candidate_id": "REQ-999", "kind": "freeze", "value": None, "reason": "planted"}
        )
        return _call("ParsedConstraints", {"constraints": out})

    def _extract(self, prompt: str) -> AIMessage:
        """Copy values from the page like a careful model, plus two planted mistakes that code must
        reject: a number missing from its quote, and a quote that is not on the page."""
        features = re.findall(r"^- (\w+): ", prompt.split("# Task", 1)[1], flags=re.M)
        page = prompt.split("# Page", 1)[1].split("# Stopping rule", 1)[0]
        values = []
        for feature in features:
            for sentence in _sentences(page):
                if _attribute(sentence) != feature:
                    continue
                value, unit = None, None
                for u, pat in _UNITS:
                    m = re.search(pat, sentence)
                    if m and u != "percent":
                        value, unit = float(m.group(1).replace(",", "")), u
                        break
                standard = (
                    "WLTP" if "WLTP" in sentence else ("10-80%" if "10-80%" in sentence else None)
                )
                values.append(
                    {
                        "feature": feature,
                        "found": True,
                        "value": value,
                        "unit": unit,
                        "test_standard": standard,
                        "region": None,
                        "variant": None,
                        "quote": sentence,
                    }
                )
                break
        if values:
            bad = dict(values[0], value=999.0, unit="km")  # number not in the quote: value dropped
            values.append(bad)
            values.append(dict(values[0], quote="This sentence is not on the page at all."))
        return _call("ExtractionOutput", {"values": values})

    def _judge(self, prompt: str) -> AIMessage:
        """First answer breaks the guard (invented number, unsupported 'widespread', unknown id);
        after the revision prompt it answers from the package. reliable_software stays wrong."""
        feature = re.search(r"^# Feature: .+? \((.+?)\)$", prompt, flags=re.M).group(1)
        customers = prompt.split("## Customers", 1)[1].split("\n## ", 1)[0]
        lines = re.findall(r"^- \[(F-[\w-]+)\] (\w+), (.+)$", customers, flags=re.M)
        revised = "Guard violations" in prompt
        if not revised or feature == "reliable_software":
            return _call(
                "JudgeOutput",
                {
                    "assessment": "gap",
                    "what_exactly": "Everything",
                    "widespread": "widespread",
                    "certainty": "high",
                    "brand_or_safety_relevant": False,
                    "reasoning": [
                        {"text": "99% of customers complain.", "cited_ids": ["F-feedback-999"]}
                    ],
                },
            )
        if not lines:
            return _call(
                "JudgeOutput",
                {
                    "assessment": "unclear",
                    "what_exactly": "No customer evidence",
                    "widespread": "unclear",
                    "certainty": "low",
                    "brand_or_safety_relevant": False,
                    "reasoning": [
                        {"text": "The package has no customer evidence.", "cited_ids": []}
                    ],
                },
            )
        fid, direction, rest = lines[0]
        assessment = {"problem": "demand", "request": "demand", "strength": "strength"}.get(
            direction, "unclear"
        )
        thin = ", thin" in rest
        text = f"Customers report a {direction} here" + (
            " but the sample is thin." if thin else "."
        )
        return _call(
            "JudgeOutput",
            {
                "assessment": assessment,
                "what_exactly": f"{direction} about {feature}",
                "widespread": "limited",
                "certainty": "low" if thin else "medium",
                "brand_or_safety_relevant": False,
                "reasoning": [{"text": text, "cited_ids": [fid]}],
            },
        )

    def _sub_themes(self, prompt: str) -> AIMessage:
        texts = re.findall(r"^\[(T\d+)\] (.+)$", prompt, flags=re.M)
        topics = {
            "Rear legroom for passengers 2": ["legroom", "rear", "back seat", "knee", "cramped"],
            "Seat ventilation in summer": ["ventilat", "cool", "sweaty"],
        }
        groups = []
        for name, words in topics.items():
            keys = [k for k, t in texts if any(w in t.lower() for w in words)]
            if keys:
                groups.append({"name": name, "keys": keys + ["T999"]})  # T999 must be dropped
        if texts:
            groups.append({"name": "Single text", "keys": [texts[0][0]]})  # < 2 keys: dropped
        return _call("SubThemeOutput", {"groups": groups})

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
            drafts.append(
                dict(drafts[0], source_ids=["web:deadbeef"], claim=f"{subject} invented claim.")
            )
        return _call("DraftFindings", {"findings": drafts})

    def _trends(self, messages: list[BaseMessage], prompt: str) -> AIMessage:
        n_tools = sum(isinstance(m, ToolMessage) for m in messages)
        if n_tools == 0:
            return _call("web_search", {"query": "megawatt charging rollout"})
        blocks = re.findall(
            r"^\[(kg:[\w-]+)\] (.+?)\n(.+?)(?=\n\n\[|\Z)", prompt, flags=re.M | re.S
        )
        trends = []
        for sid, title, text in blocks:
            sentence = _sentences(text)[0]
            draft = _draft_from_sentence(sid, sentence, "market")
            draft.update(polarity="demand", horizon="1-2y", attribute=_attribute(text))
            trends.append(
                {
                    "name": title.split(":")[-1].split("(")[0].strip(),
                    "category": "technology",
                    "findings": [draft],
                }
            )
        for sid, block in _web_blocks(messages):
            if sid.startswith("web:"):
                sentence = next(s for s in _sentences(block) if "1,200" in s)
                draft = _draft_from_sentence(sid, sentence, "market")
                draft.update(
                    value=1200.0,
                    unit="charging points",
                    attribute="fast_charging",
                    polarity="demand",
                    horizon="now",
                    evidence_quote=sentence,
                )
                trends.append(
                    {
                        "name": "High-power charging rollout",
                        "category": "technology",
                        "findings": [draft],
                    }
                )
                break
        return _call("TrendsOutput", {"trends": trends})

    def _explain(self, prompt: str) -> AIMessage:
        found = re.search(r"^\[(F-[\w-]+)\].*\n  claim: (.+)$", prompt, flags=re.M)
        if not found:
            return _call(
                "ExplainOutput",
                {"supported": False, "sentences": [], "missing": "relevant findings"},
            )
        fid, claim = found.groups()
        return _call(
            "ExplainOutput",
            {
                "supported": True,
                "missing": "",
                "sentences": [
                    {"text": claim, "cited_ids": [fid]},
                    {
                        "text": "This also holds for an unrelated finding.",
                        "cited_ids": ["F-other-999"],
                    },  # must be dropped
                    {
                        "text": "It sold 123456789 units.",
                        "cited_ids": [fid],
                    },  # invented number, must be dropped
                ],
            },
        )


def fake_models() -> tuple[ScriptedChatModel, ScriptedChatModel, HashEmbeddings, FakeAnalyst]:
    analyst = FakeAnalyst()
    return (
        ScriptedChatModel(responder=analyst),
        ScriptedChatModel(responder=analyst),
        HashEmbeddings(),
        analyst,
    )
