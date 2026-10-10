"""Knowledge-layer records the agents rely on (AGENT_SPEC §4.1–4.2).

PROPOSED by the `src/agent/` builder: the minimum fields the agents read. They live here (not in
`src/agent/`) because the hand-off `ProductBrief` embeds `ModelNode`. When the real `src.knowledge`
modules land, their results are coerced into these records by `src/agent/tools/knowledge.py`.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class _Record(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class AttributeValue(_Record):
    node_id: str
    attribute: str
    value: float | str
    unit: str | None = None
    source_note: str = ""
    as_of: dt.date | None = None  # optional: lets competition_agent detect stale values


class ModelNode(_Record):
    node_id: str
    model_code: str | None = None  # registry code, e.g. "G60"; None for most competitor models
    name: str
    brand: str
    segment: str
    powertrain: str | None = None
    regions: list[str] = []  # regions the model is sold in / has data for
    attributes: list[AttributeValue] = []


class FeedbackItem(_Record):
    item_id: str
    text: str
    channel: str
    market: str | None = None
    date: dt.date | None = None
    rating: float | None = None
    model: str | None = None


class DocChunk(_Record):
    node_id: str
    doc_title: str
    text: str
    url: str | None = None
    published: dt.date | None = None
    regions: list[str] = []  # empty = not region-specific


class FeedbackFilter(_Record):
    models: list[str] = []
    markets: list[str] = []
    since: dt.date | None = None
    limit: int | None = None


class SalesRow(_Record):
    model: str
    market: str
    period: str
    units: int
