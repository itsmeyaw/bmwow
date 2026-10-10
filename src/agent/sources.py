"""Source construction, the per-agent source registry and tool budgets.

Source ids are always assigned here, by code (AGENT_SPEC §6.0.2).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.models.evidence import EXCERPT_MAX_CHARS, Source

from .tools.knowledge import AttributeValue, DocChunk, FeedbackItem, ModelNode

_WS = re.compile(r"\s+")
_TRACKING_PARAMS = re.compile(r"^(utm_.*|gclid|fbclid|mc_cid|mc_eid|ref|ref_src)$", re.I)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clip(text: str, limit: int = EXCERPT_MAX_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def short_hash(text: str, n: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)))
    return urlunsplit((scheme, host, path, query, ""))


def web_source_id(url: str) -> str:
    return "web:" + short_hash(canonical_url(url))


# ---------------------------------------------------------------- renderers / constructors


def render_attribute(model_name: str, av: AttributeValue) -> str:
    unit = f" {av.unit}" if av.unit else ""
    note = f" ({av.source_note})" if av.source_note else ""
    as_of = f" [as of {av.as_of.isoformat()}]" if av.as_of else ""
    return f"{model_name}: {av.attribute} = {av.value}{unit}{note}{as_of}"


def render_model(model: ModelNode) -> str:
    code = f" | code={model.model_code}" if model.model_code else ""
    regions = f" | regions={','.join(model.regions)}" if model.regions else ""
    head = (f"{model.name}{code} | brand={model.brand} | segment={model.segment} "
            f"| powertrain={model.powertrain or 'n/a'}{regions}")
    lines = [head] + [render_attribute(model.name, av) for av in model.attributes]
    return clip("\n".join(lines))


def attribute_source(model: ModelNode, av: AttributeValue) -> Source:
    return Source(
        id=f"kg:{av.node_id}",
        kind="ontology",
        ref=av.node_id,
        title=f"{model.name} – {av.attribute}",
        excerpt=clip(render_attribute(model.name, av)),
        retrieved_at=utcnow(),
    )


def model_source(model: ModelNode) -> Source:
    return Source(
        id=f"kg:{model.node_id}",
        kind="ontology",
        ref=model.node_id,
        title=model.name,
        excerpt=render_model(model),
        retrieved_at=utcnow(),
    )


def doc_source(chunk: DocChunk) -> Source:
    published = f" ({chunk.published.isoformat()})" if chunk.published else ""
    return Source(
        id=f"kg:{chunk.node_id}",
        kind="ontology",
        ref=chunk.node_id,
        title=f"{chunk.doc_title}{published}",
        excerpt=clip(chunk.text),
        retrieved_at=utcnow(),
    )


def feedback_source(item: FeedbackItem) -> Source:
    meta = ", ".join(x for x in (item.channel, item.market or "", item.model or "") if x)
    return Source(
        id=f"fb:{item.item_id}",
        kind="feedback",
        ref=item.item_id,
        title=meta,
        excerpt=clip(item.text),  # verbatim
        retrieved_at=utcnow(),
    )


def sql_source(function: str, params: dict[str, Any], rendered_rows: str, title: str = "") -> Source:
    ref = f"{function}({json.dumps(params, sort_keys=True, default=str)})"
    return Source(
        id="sql:" + short_hash(ref, 10),
        kind="sql",
        ref=ref,
        title=title or function,
        excerpt=clip(rendered_rows),
        retrieved_at=utcnow(),
    )


# ---------------------------------------------------------------- registry


class SourceRegistry:
    """Every source an agent touched, keyed by id, plus the full text behind it.

    Pages and documents are longer than an excerpt may be. Findings from the LLM carry a verbatim
    `evidence_quote`; `attach_quote` checks it against the full text and the final excerpt of the
    source is built from the verified quotes, so the excerpt contains what the claims rely on.
    """

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._full_text: dict[str, str] = {}
        self._quotes: dict[str, list[str]] = {}

    def add(self, source: Source, full_text: str | None = None) -> Source:
        existing = self._sources.get(source.id)
        if existing is None:
            self._sources[source.id] = source
            existing = source
        if full_text and len(full_text) > len(self._full_text.get(source.id, "")):
            self._full_text[source.id] = full_text
        return existing

    def get(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def __contains__(self, source_id: str) -> bool:
        return source_id in self._sources

    def full_text(self, source_id: str) -> str:
        return self._full_text.get(source_id) or (self._sources[source_id].excerpt if source_id in self else "")

    def find_quote(self, source_id: str, quote: str) -> str | None:
        """Return the quote if it appears verbatim (whitespace-insensitive) in the source text."""
        quote = normalize_ws(quote).strip(" \"'“”…")
        if len(quote) < 8 or source_id not in self:
            return None
        if quote.lower() in normalize_ws(self.full_text(source_id)).lower():
            return quote
        return None

    def attach_quote(self, source_id: str, quote: str) -> bool:
        found = self.find_quote(source_id, quote)
        if found is None:
            return False
        quotes = self._quotes.setdefault(source_id, [])
        if found not in quotes:
            quotes.append(found)
        return True

    def sources(self, only: set[str] | None = None) -> list[Source]:
        out: list[Source] = []
        for sid, src in self._sources.items():
            if only is not None and sid not in only:
                continue
            quotes = self._quotes.get(sid)
            if quotes:
                src = src.model_copy(update={"excerpt": clip(" … ".join(quotes))})
            out.append(src)
        return out


# ---------------------------------------------------------------- budgets


@dataclass
class Budget:
    """Tool-call and scrape budget (AGENT_SPEC §6.0.6). Child budgets also draw from their parent."""

    max_tool_calls: int
    max_pages: int
    parent: Budget | None = None
    tool_calls: int = 0
    pages: int = 0
    exhausted_events: list[str] = field(default_factory=list)

    def child(self, max_tool_calls: int, max_pages: int) -> Budget:
        return Budget(max_tool_calls=max_tool_calls, max_pages=max_pages, parent=self)

    def has(self, kind: Literal["call", "page"]) -> bool:
        ok = self.tool_calls < self.max_tool_calls if kind == "call" else self.pages < self.max_pages
        return ok and (self.parent is None or self.parent.has(kind))

    def take(self, *kinds: Literal["call", "page"]) -> bool:
        """Take one unit of each kind, all or nothing."""
        missing = [k for k in kinds if not self.has(k)]
        if missing:
            self.exhausted_events.extend(missing)
            return False
        for kind in kinds:
            node: Budget | None = self
            while node is not None:
                if kind == "call":
                    node.tool_calls += 1
                else:
                    node.pages += 1
                node = node.parent
        return True
