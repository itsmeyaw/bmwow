from pathlib import Path

import pytest

from bmwow.agent.models.evidence import SearchLocale
from bmwow.agent.supervisor import build_graph
from bmwow.agent.tools import web_search
from bmwow.agent.tools.html_text import html_to_text
from bmwow.agent.tools.web_corpus import CorpusPage, CorpusSearchBackend
from bmwow.agent.tools.web_search import OfflineCacheMiss
from scripts import build_web_corpus
from tests.fakes.data import WEB_PAGES

EU = SearchLocale(country="de", lang="en")
CN = SearchLocale(country="cn", lang="zh")


def write_corpus(root: Path) -> Path:
    """The fake web pages as a saved corpus: competitor pages tagged, D only in the EU."""
    (root / "pages").mkdir(parents=True)
    for i, (url, (title, text)) in enumerate(WEB_PAGES.items()):
        name = (
            title.split(" –")[0]
            .split(" technical")[0]
            .split(" review")[0]
            .split(" specifications")[0]
        )
        competitor = name if name.startswith("Competitor") else None
        region = "EU" if competitor == "Competitor D Sedan" else "GLOBAL"
        page = CorpusPage(
            url=url,
            title=title,
            retrieved_at="2026-10-11T00:00:00+00:00",
            markdown=text,
            tags=[f"competitor:{competitor}"] if competitor else ["trend", "fast_charging"],
            region=region,
            countries=build_web_corpus.REGION_COUNTRIES[region],
        )
        (root / "pages" / f"{i}.json").write_text(page.model_dump_json())
    return root


def test_html_to_text_keeps_tables_and_drops_chrome():
    html = """<html><head><title>A6 e-tron data</title><script>var x=1</script></head><body>
    <nav>Menu Models Configurator</nav><h2>Technical data</h2><p>Range &amp; charging</p>
    <table><tr><th>Range (WLTP)</th><td>up to 756&nbsp;km</td></tr><tr><td>DC 10-80%</td><td>21 min</td></tr></table>
    <footer>Imprint</footer></body></html>"""
    title, text = html_to_text(html)
    assert title == "A6 e-tron data"
    assert "| Range (WLTP) | up to 756 km |" in text and "| DC 10-80% | 21 min |" in text
    assert "## Technical data" in text and "Range & charging" in text
    assert "Menu" not in text and "Imprint" not in text and "var x" not in text


async def test_corpus_search_ranks_boosts_and_respects_regions(tmp_path):
    backend = CorpusSearchBackend(write_corpus(tmp_path))
    hits = await backend.search_pages("Competitor C Sedan range WLTP km", limit=3, locale=EU)
    assert hits and hits[0].url.endswith("competitor-c-sedan/specs")
    eu = [p.url for p in await backend.search_pages("Competitor D Sedan rear legroom", 5, EU)]
    cn = [p.url for p in await backend.search_pages("Competitor D Sedan rear legroom", 5, CN)]
    assert any("competitor-d" in u for u in eu) and not any("competitor-d" in u for u in cn)
    page = await backend.scrape_page("https://www.example.com/competitor-c-sedan/specs/")
    assert "575 km" in page.markdown and page.retrieved_at.startswith("2026-10-11")
    with pytest.raises(OfflineCacheMiss):
        await backend.scrape_page("https://example.com/not-saved")
    assert await backend.search_pages("zzz unmatched words", 5, EU) == []


async def test_pipeline_reads_competitors_from_the_corpus_only(
    tmp_path, analysis_request, fake_env
):
    web_search.set_search_backend(CorpusSearchBackend(write_corpus(tmp_path / "corpus")))
    analysis = (await build_graph().ainvoke({"run_id": "corpus", "request": analysis_request}))[
        "analysis"
    ]
    web = [
        f
        for f in analysis.reports["competition"].findings
        if any(s.startswith("web:") for s in f.source_ids)
    ]
    assert web and any(f.quantity and "wltp" in f.quantity.qualifier.lower() for f in web)
    assert fake_env["provider"].searches == []  # the live provider was never asked
    sources = {s.id: s for s in analysis.reports["competition"].sources}
    assert all(
        sources[s].retrieved_at.year == 2026
        for f in web
        for s in f.source_ids
        if s.startswith("web:")
    )


def test_build_saves_pages_reports_failures_and_keeps_existing(tmp_path, monkeypatch):
    long_html = (
        "<html><head><title>Spec</title></head><body>"
        + "<p>Range 600 km WLTP.</p>" * 40
        + "</body></html>"
    )
    pages = {
        "https://example.com/ok": ("text/html; charset=utf-8", long_html),
        "https://example.com/js": ("text/html", "<html><body><div id=app></div></body></html>"),
        "https://example.com/pdf": ("application/pdf", "%PDF"),
    }
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return pages[url]

    monkeypatch.setattr(build_web_corpus, "fetch", fake_fetch)
    entries = [build_web_corpus.SourceEntry(url=u, tags=["x"], region="EU") for u in pages]
    results = {r["url"]: r for r in build_web_corpus.build(entries, tmp_path, refresh=False)}
    assert results["https://example.com/ok"]["status"] == "saved"
    assert "JavaScript" in results["https://example.com/js"]["reason"]
    assert "content type" in results["https://example.com/pdf"]["reason"]
    saved = CorpusPage.model_validate_json(
        build_web_corpus.page_path(tmp_path, "https://example.com/ok").read_text()
    )
    assert saved.countries and "de" in saved.countries and "600 km" in saved.markdown
    again = {
        r["url"]: r["status"] for r in build_web_corpus.build(entries, tmp_path, refresh=False)
    }
    assert again["https://example.com/ok"] == "kept" and calls.count("https://example.com/ok") == 1


def test_sources_file_is_valid():
    import yaml

    entries = [
        build_web_corpus.SourceEntry.model_validate(x)
        for x in yaml.safe_load(build_web_corpus.SOURCES.read_text()) or []
    ]
    assert all(
        e.url.startswith("https://") and e.region in build_web_corpus.REGION_COUNTRIES
        for e in entries
    )
