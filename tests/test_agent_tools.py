import re

import pytest

from src.agent import router
from src.agent.config import get_settings
from src.agent.sources import Budget, SourceRegistry, canonical_url, web_source_id
from src.agent.tools import graph_rag, sql_rag, web_search
from src.agent.tools.web_search import CachedSearchBackend, OfflineCacheMiss
from src.models.evidence import EXCERPT_MAX_CHARS, SearchLocale
from tests.fakes.data import REF_CODE, REFERENCE, SEGMENT
from tests.fakes.web import FakePageProvider, NoNetworkProvider

URL = "https://example.com/competitor-c-sedan/specs"
LOCALES = {"EU": SearchLocale(country="de", lang="en"), "CN": SearchLocale(country="cn", lang="zh")}


async def test_graph_rag_returns_ontology_sources():
    got = await graph_rag.search_documents("charging", ["study"], ["EU"], 3)
    assert got.data and len(got.sources) == len(got.data)
    for chunk, src in zip(got.data, got.sources, strict=True):
        assert (
            src.id == f"kg:{chunk.node_id}" and src.kind == "ontology" and src.ref == chunk.node_id
        )
        assert src.excerpt and len(src.excerpt) <= EXCERPT_MAX_CHARS


async def test_sql_rag_renders_rows_into_excerpt():
    got = await sql_rag.sales_volume([REF_CODE], ["DE"])
    (src,) = got.sources
    assert src.kind == "sql" and re.fullmatch(r"sql:[0-9a-f]{10}", src.id)
    assert "sales_volume(" in src.ref and '"DE"' in src.ref
    for row in got.data:
        assert f"{row.period} | {row.units} units" in src.excerpt


async def test_router_is_the_single_switch():
    assert router.route("sales_volume") == "sql_rag"
    assert router.route("competitor_live_specs") == "web_search"
    got = await router.fetch("portfolio", SEGMENT, ["EU"])
    assert REFERENCE in {m.name for m in got.data}
    with pytest.raises(ValueError):
        await router.fetch("live_trends", "x")


def test_web_source_id_is_stable_per_canonical_url():
    a = web_source_id("https://www.Example.com/competitor-c-sedan/specs/?utm_source=x#top")
    assert a == web_source_id(URL) and re.fullmatch(r"web:[0-9a-f]{8}", a)
    assert canonical_url(URL + "?b=2&a=1") == canonical_url(URL + "?a=1&b=2")


async def test_web_tools_show_citable_ids_and_register_sources():
    registry, errors = SourceRegistry(), []
    tools = {t.name: t for t in web_search.make_web_tools(registry, Budget(10, 5), errors, LOCALES)}
    out = await tools["web_search"].ainvoke({"query": "Competitor C range"})
    ids = re.findall(r"\[(web:[0-9a-f]{8})\]", out)
    assert ids and all(i in registry for i in ids)
    src = registry.get(web_source_id(URL))
    assert src.kind == "web" and src.ref == canonical_url(URL) and src.excerpt
    page = await tools["scrape_url"].ainvoke({"url": URL, "focus": "range km"})
    assert page.startswith(f"[{web_source_id(URL)}]") and "575 km" in page
    assert not errors


async def test_web_tools_respect_budget():
    registry = SourceRegistry()
    tools = {t.name: t for t in web_search.make_web_tools(registry, Budget(1, 0), [], LOCALES)}
    assert "BUDGET EXHAUSTED" in await tools["scrape_url"].ainvoke({"url": URL})  # no page budget
    assert "[web:" in await tools["web_search"].ainvoke({"query": "Competitor C"})
    assert "BUDGET EXHAUSTED" in await tools["web_search"].ainvoke({"query": "Competitor C"})


async def test_web_cache_hits_on_second_call(tmp_path):
    provider = FakePageProvider()
    backend = CachedSearchBackend(provider, tmp_path / "cache", offline=False)
    first = await backend.search("Competitor C range", limit=3)
    second = await backend.search("  competitor c   RANGE ", limit=3)  # normalized key
    assert [s.id for s in first] == [s.id for s in second]
    assert len(provider.calls) == 1 and backend.hits == 1 and backend.misses == 1
    await backend.scrape(URL)
    await backend.scrape("https://www.example.com/competitor-c-sedan/specs/")
    assert sum(c.startswith("scrape:") for c in provider.calls) == 1


async def test_offline_mode_serves_cache_and_raises_on_miss(tmp_path):
    online = CachedSearchBackend(FakePageProvider(), tmp_path / "cache", offline=False)
    await online.search("Competitor C range")
    offline = CachedSearchBackend(NoNetworkProvider(), tmp_path / "cache", offline=True)
    assert await offline.search("Competitor C range")
    with pytest.raises(OfflineCacheMiss):
        await offline.search("something never cached")
    with pytest.raises(OfflineCacheMiss):
        await offline.scrape("https://example.com/never")


async def test_offline_mode_from_settings(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "true")
    get_settings.cache_clear()
    web_search.set_search_backend(None)
    backend = web_search.get_search_backend()
    assert backend.offline and backend.provider is None
    with pytest.raises(OfflineCacheMiss):
        await backend.search("anything")
