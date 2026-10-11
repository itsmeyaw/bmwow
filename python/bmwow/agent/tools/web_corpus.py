"""A curated, saved web corpus as the agents' search backend (SEARCH_BACKEND=corpus).

The corpus is built once from an approved URL list (scripts/build_web_corpus.py) into
`data/web_corpus/pages/*.json`. At runtime `web_search` ranks the saved pages for a query (BM25 over
title + text + tags, boosted for pages tagged with a subject named in the query) and keeps only pages
for the searched region; `scrape_url` returns a saved page. Both return the same `WebPage` records as
the live provider, so Sources, findings and reports are unchanged. Nothing is fetched at runtime.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from bmwow.agent.models.evidence import SearchLocale, Source

from ..sources import canonical_url
from .web_search import OfflineCacheMiss, WebPage, page_to_source

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "and",
    "or",
    "for",
    "to",
    "on",
    "with",
    "by",
    "is",
    "at",
    "de",
}
TAG_BOOST = 3.0


class CorpusPage(BaseModel):
    """One saved page. `countries` empty = applies to every region."""

    url: str
    title: str
    retrieved_at: str  # ISO timestamp of the download
    markdown: str
    tags: list[str] = Field(
        default_factory=list
    )  # e.g. "competitor:Audi A6", "fast_charging", "trend"
    region: str = "GLOBAL"
    countries: list[str] = Field(default_factory=list)  # lower-case country codes
    why: str = ""


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class CorpusSearchBackend:
    """Same interface as CachedSearchBackend: search_pages / scrape_page / search / scrape."""

    def __init__(self, corpus_dir: Path) -> None:
        self.corpus_dir = corpus_dir
        files = sorted((corpus_dir / "pages").glob("*.json")) if corpus_dir.exists() else []
        self.pages = [CorpusPage.model_validate_json(f.read_text(encoding="utf-8")) for f in files]
        self.by_url = {canonical_url(p.url): p for p in self.pages}
        self._docs = [
            Counter(_tokens(f"{p.title} {p.title} {p.markdown} {' '.join(p.tags)}"))
            for p in self.pages
        ]
        self._len = [sum(d.values()) for d in self._docs]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 1.0
        df: Counter[str] = Counter()
        for d in self._docs:
            df.update(d.keys())
        n = max(1, len(self.pages))
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.searches: list[tuple[str, SearchLocale | None]] = []

    def _in_region(self, page: CorpusPage, locale: SearchLocale | None) -> bool:
        return locale is None or not page.countries or locale.country.lower() in page.countries

    def _score(self, i: int, terms: list[str], query: str) -> float:
        doc, length = self._docs[i], self._len[i]
        score = 0.0
        for t in set(terms):
            tf = doc.get(t, 0)
            if tf:
                score += (
                    self._idf.get(t, 0.0)
                    * tf
                    * 2.2
                    / (tf + 1.2 * (0.25 + 0.75 * length / self._avg))
                )
        q = query.lower()
        for tag in self.pages[i].tags:
            name = tag.split(":", 1)[1] if tag.startswith("competitor:") else ""
            if name and name.lower() in q:
                score += TAG_BOOST
        return score

    is_local = True  # searches cost nothing: callers need not spend their web-call budget on them

    def competitors(self, regions: list[str], segment: str | None = None) -> dict[str, list[str]]:
        """Competitor name -> requested regions it has pages for (from `competitor:<name>` tags).
        GLOBAL pages count for every requested region. With a segment, pages tagged with another
        `segment:<name>` are left out, so only same-class competitors are compared."""
        out: dict[str, list[str]] = {}
        for page in self.pages:
            tagged = {t.split(":", 1)[1].strip() for t in page.tags if t.startswith("segment:")}
            if segment and tagged and segment not in tagged:
                continue
            for tag in page.tags:
                if not tag.startswith("competitor:"):
                    continue
                name = tag.split(":", 1)[1].strip()
                covered = regions if page.region in ("", "GLOBAL") else [page.region]
                for region in covered:
                    if region in regions and region not in out.setdefault(name, []):
                        out[name].append(region)
        return {n: sorted(r, key=regions.index) for n, r in sorted(out.items()) if r}

    async def search_pages(
        self, query: str, limit: int = 5, locale: SearchLocale | None = None
    ) -> list[WebPage]:
        self.searches.append((query, locale))
        terms = _tokens(query)
        ranked = sorted(
            (
                (self._score(i, terms, query), i)
                for i, p in enumerate(self.pages)
                if self._in_region(p, locale)
            ),
            key=lambda x: (-x[0], self.pages[x[1]].url),
        )
        return [self._page(self.pages[i]) for s, i in ranked[:limit] if s > 0]

    async def scrape_page(self, url: str) -> WebPage:
        page = self.by_url.get(canonical_url(url))
        if page is None:
            raise OfflineCacheMiss(f"{url} is not in the web corpus")
        return self._page(page)

    async def search(
        self, query: str, limit: int = 5, locale: SearchLocale | None = None
    ) -> list[Source]:
        return [page_to_source(p, query) for p in await self.search_pages(query, limit, locale)]

    async def scrape(self, url: str) -> Source:
        return page_to_source(await self.scrape_page(url))

    @staticmethod
    def _page(p: CorpusPage) -> WebPage:
        return WebPage(url=p.url, title=p.title, markdown=p.markdown, retrieved_at=p.retrieved_at)
