"""Feedback item deduplication (portable: no embeddings, no clustering).

Items that carry evidence references are duplicates only when they reference the same evidence, so
identical comments from distinct records stay distinct. Legacy items without references fall back to
normalized text.
"""

from __future__ import annotations

import re
import unicodedata

from .knowledge import FeedbackItem


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def exact_dedupe(items: list[FeedbackItem]) -> list[FeedbackItem]:
    seen: set[tuple] = set()
    out: list[FeedbackItem] = []
    for item in items:
        text = normalize_text(item.text)
        key = (
            ("evidence", tuple(sorted((ref.source_id, ref.evidence_id) for ref in item.references)))
            if item.references
            else ("legacy_text", text)
        )
        if text and key not in seen:
            seen.add(key)
            out.append(item)
    return out
