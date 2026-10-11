"""Fake page provider for the web cache (no network)."""

from __future__ import annotations

import re

from bmwow.agent.models.evidence import SearchLocale
from bmwow.agent.sources import canonical_url, utcnow
from bmwow.agent.tools.web_search import WebPage

from .data import WEB_PAGES


class FakePageProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.searches: list[tuple[str, SearchLocale | None]] = []

    def _page(self, url: str) -> WebPage:
        title, text = WEB_PAGES[url]
        return WebPage(url=url, title=title, markdown=text, retrieved_at=utcnow().isoformat())

    async def search_pages(
        self, query: str, limit: int, locale: SearchLocale | None = None
    ) -> list[WebPage]:
        self.calls.append(f"search:{query}")
        self.searches.append((query, locale))
        terms = set(re.findall(r"[a-z0-9]+", query.lower())) - {"sedan", "the", "of", "in"}
        scored = []
        for url, (title, text) in WEB_PAGES.items():
            overlap = len(terms & set(re.findall(r"[a-z0-9]+", (title + " " + text).lower())))
            if overlap:
                scored.append((overlap, url))
        scored.sort(key=lambda x: -x[0])
        return [self._page(u) for _, u in scored[:limit]]

    async def scrape_page(self, url: str) -> WebPage:
        self.calls.append(f"scrape:{url}")
        for known in WEB_PAGES:
            if canonical_url(known) == canonical_url(url):
                return self._page(known)
        raise ValueError(f"404 {url}")


class NoNetworkProvider:
    """Fails loudly if anything tries to go past the cache."""

    async def search_pages(
        self, query: str, limit: int, locale: SearchLocale | None = None
    ) -> list[WebPage]:
        raise AssertionError(f"network search attempted: {query}")

    async def scrape_page(self, url: str) -> WebPage:
        raise AssertionError(f"network scrape attempted: {url}")
