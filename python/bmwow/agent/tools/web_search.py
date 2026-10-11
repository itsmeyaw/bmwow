"""Web search and scraping behind `SearchBackend`, with an on-disk cache (SPEC §6.5).

Every call goes through `data/processed/web_cache/` (key = normalized query or canonical URL).
With OFFLINE_MODE=true only the cache is served and a missing key raises `OfflineCacheMiss`.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from langchain_core.tools import BaseTool, StructuredTool

from bmwow.agent.models.evidence import SearchLocale, Source

from ..config import get_settings
from ..sources import (
    Budget,
    SourceRegistry,
    canonical_url,
    clip,
    normalize_ws,
    short_hash,
    utcnow,
    web_source_id,
)

SEARCH_EXCERPT_CHARS = 700
SCRAPE_TOOL_CHARS = 3500
CHUNK_CHARS = 1000
_TOKEN = re.compile(r"[a-z0-9]+")


class SearchBackend(Protocol):
    # excerpt = best-matching chunk; `locale` = the region's search locale (SPEC §6.0.10)
    async def search(
        self, query: str, limit: int = 5, locale: SearchLocale | None = None
    ) -> list[Source]: ...
    async def scrape(self, url: str) -> Source: ...  # full page markdown → chunked


class OfflineCacheMiss(RuntimeError):
    pass


@dataclass
class WebPage:
    url: str
    title: str
    markdown: str
    retrieved_at: str  # ISO timestamp of the original fetch


class PageProvider(Protocol):
    """Provider-level fetcher (Firecrawl, …). Only the cache layer talks to it."""

    async def search_pages(
        self, query: str, limit: int, locale: SearchLocale | None
    ) -> list[WebPage]: ...
    async def scrape_page(self, url: str) -> WebPage: ...


# ---------------------------------------------------------------- chunking


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        while len(p) > size:  # hard-split very long paragraphs
            if current:
                chunks.append(current)
                current = ""
            chunks.append(p[:size])
            p = p[size:]
        if current and len(current) + len(p) + 2 > size:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        chunks.append(current)
    return chunks


def rank_chunks(text: str, query: str) -> list[str]:
    chunks = chunk_text(text)
    terms = set(_TOKEN.findall(query.lower()))
    if not terms:
        return chunks
    scored = sorted(
        enumerate(chunks), key=lambda ic: (-len(terms & set(_TOKEN.findall(ic[1].lower()))), ic[0])
    )
    return [c for _, c in scored]


def page_to_source(page: WebPage, query: str = "") -> Source:
    ranked = rank_chunks(page.markdown, query) if query else chunk_text(page.markdown)
    return Source(
        id=web_source_id(page.url),
        kind="web",
        ref=canonical_url(page.url),
        title=page.title,
        excerpt=clip(ranked[0] if ranked else page.title or page.url),
        retrieved_at=datetime.fromisoformat(page.retrieved_at),
    )


# ---------------------------------------------------------------- Firecrawl


class FirecrawlProvider:
    def __init__(self, api_key: str) -> None:
        from firecrawl import AsyncFirecrawl

        if not api_key:
            raise RuntimeError("FIRECRAWL_API_KEY is not set")
        self.client = AsyncFirecrawl(api_key=api_key)

    @staticmethod
    def _page(doc: Any, fallback_url: str = "") -> WebPage:
        meta = getattr(doc, "metadata", None)
        url = (
            getattr(meta, "source_url", None)
            or getattr(meta, "url", None)
            or getattr(doc, "url", None)
            or fallback_url
        )
        title = getattr(meta, "title", None) or getattr(doc, "title", None) or ""
        text = getattr(doc, "markdown", None) or getattr(doc, "description", None) or ""
        return WebPage(url=url, title=title, markdown=text, retrieved_at=utcnow().isoformat())

    async def search_pages(
        self, query: str, limit: int, locale: SearchLocale | None
    ) -> list[WebPage]:
        from firecrawl.v2.types import Location, ScrapeOptions

        country = locale.country.upper() if locale else None
        location = Location(country=country, languages=[locale.lang]) if locale else None
        data = await self.client.search(
            query,
            limit=limit,
            country=country,
            scrape_options=ScrapeOptions(
                formats=["markdown"], only_main_content=True, location=location
            ),
        )
        return [p for p in (self._page(d) for d in (data.web or [])) if p.url and p.markdown]

    async def scrape_page(self, url: str) -> WebPage:
        doc = await self.client.scrape(url, formats=["markdown"], only_main_content=True)
        return self._page(doc, fallback_url=url)


# ---------------------------------------------------------------- cache


class CachedSearchBackend:
    """`SearchBackend` implementation: provider + on-disk cache + offline mode."""

    def __init__(self, provider: PageProvider | None, cache_dir: Path, offline: bool) -> None:
        self.provider = provider
        self.cache_dir = cache_dir
        self.offline = offline
        self.hits = 0
        self.misses = 0

    def _path(self, kind: str, key: str) -> Path:
        return self.cache_dir / kind / f"{short_hash(key, 16)}.json"

    async def _cached(self, kind: str, key: str, fetch: Any) -> list[WebPage]:
        path = self._path(kind, key)
        if path.exists():
            self.hits += 1
            return [WebPage(**p) for p in json.loads(path.read_text())["pages"]]
        if self.offline or self.provider is None:
            raise OfflineCacheMiss(f"web cache miss in offline mode: {key}")
        self.misses += 1
        pages = await fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"key": key, "pages": [asdict(p) for p in pages]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
        return pages

    async def search_pages(
        self, query: str, limit: int = 5, locale: SearchLocale | None = None
    ) -> list[WebPage]:
        where = f"{locale.country}-{locale.lang}:" if locale else ""
        key = f"search:{limit}:{where}{normalize_ws(query).lower()}"
        return await self._cached(
            "search", key, lambda: self.provider.search_pages(query, limit, locale)
        )  # type: ignore[union-attr]

    async def scrape_page(self, url: str) -> WebPage:
        key = f"scrape:{canonical_url(url)}"
        pages = await self._cached("scrape", key, lambda: _one(self.provider.scrape_page(url)))  # type: ignore[union-attr]
        return pages[0]

    async def search(
        self, query: str, limit: int = 5, locale: SearchLocale | None = None
    ) -> list[Source]:
        return [page_to_source(p, query) for p in await self.search_pages(query, limit, locale)]

    async def scrape(self, url: str) -> Source:
        return page_to_source(await self.scrape_page(url))


async def _one(coro: Any) -> list[WebPage]:
    return [await coro]


_backend: CachedSearchBackend | None = None


def set_search_backend(backend: CachedSearchBackend | None) -> None:
    global _backend
    _backend = backend


def get_search_backend() -> CachedSearchBackend:
    global _backend
    if _backend is None:
        s = get_settings()
        provider: PageProvider | None = None
        if not s.offline_mode:
            if s.search_backend == "firecrawl":
                provider = FirecrawlProvider(s.firecrawl_api_key)
            else:
                raise NotImplementedError(
                    f"SEARCH_BACKEND={s.search_backend} is not implemented yet"
                )
        _backend = CachedSearchBackend(provider, s.web_cache_dir, s.offline_mode)
    return _backend


# ---------------------------------------------------------------- LangChain tools


def make_web_tools(
    registry: SourceRegistry, budget: Budget, errors: list[str], locales: dict[str, SearchLocale]
) -> list[BaseTool]:
    """`web_search` and `scrape_url` tools. Results show source ids ([web:xxxxxxxx]) for citation.

    Every search runs in the locale of one of `locales` (region -> locale; SPEC §6.0.10). With
    several regions the model picks one per search; unknown or empty picks use the first region.
    """
    if not locales:
        raise ValueError("web tools need at least one region search locale")
    default_region = next(iter(locales))

    async def web_search(query: str, region: str = "") -> str:
        if not budget.take("call"):
            return "BUDGET EXHAUSTED: stop calling tools and return your final answer now."
        region = region.strip().upper()
        locale = locales.get(region) or locales[default_region]
        try:
            pages = await get_search_backend().search_pages(query, limit=5, locale=locale)
        except Exception as exc:  # report to the model and the agent, keep the loop alive
            errors.append(f"web_search({query!r}): {exc}")
            return f"ERROR: {exc}"
        if not pages:
            return "No results."
        out = []
        for page in pages:
            src = registry.add(page_to_source(page, query), full_text=page.markdown)
            best = (
                rank_chunks(page.markdown, query)[0][:SEARCH_EXCERPT_CHARS] if page.markdown else ""
            )
            out.append(f"[{src.id}] {page.title} — {src.ref}\n{best}")
        return "\n\n".join(out)

    async def scrape_url(url: str, focus: str = "") -> str:
        if not budget.take("call", "page"):
            return "BUDGET EXHAUSTED: stop calling tools and return your final answer now."
        try:
            page = await get_search_backend().scrape_page(url)
        except Exception as exc:
            errors.append(f"scrape_url({url!r}): {exc}")
            return f"ERROR: {exc}"
        src = registry.add(page_to_source(page, focus), full_text=page.markdown)
        body, used = [], 0
        for chunk in rank_chunks(page.markdown, focus) if focus else chunk_text(page.markdown):
            if used + len(chunk) > SCRAPE_TOOL_CHARS:
                break
            body.append(chunk)
            used += len(chunk)
        return f"[{src.id}] {page.title} — {src.ref}\n\n" + "\n\n---\n\n".join(body)

    return [
        StructuredTool.from_function(
            coroutine=web_search,
            name="web_search",
            description="Search the web. Returns up to 5 results with citable ids [web:...] and the best-matching "
            "passage."
            + (
                f" `region` = one of {', '.join(locales)}: the market whose local results "
                f"you want (default {default_region})."
                if len(locales) > 1
                else ""
            ),
        ),
        StructuredTool.from_function(
            coroutine=scrape_url,
            name="scrape_url",
            description="Fetch a page as markdown. `focus` = words to rank passages by (e.g. 'range WLTP km'). "
            "Returns the page's citable id [web:...] and its most relevant passages.",
        ),
    ]
