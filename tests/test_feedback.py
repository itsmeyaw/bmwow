import re
from collections import Counter

import pytest

from src.agent.supervisor import build_graph
from src.agent.tools.feedback_stats import analyze_feedback, exact_dedupe
from src.models.evidence import AnalysisRequest
from tests.fakes.data import CN_ONLY_THEME, REF_CODE, THEMES, feedback, theme_for
from tests.fakes.llm import HashEmbeddings


@pytest.mark.parametrize("method", ["auto", "kmeans"])
async def test_planted_themes_are_recovered(method):
    result = await analyze_feedback(feedback(), HashEmbeddings(), method)
    dominant = set()
    for cluster in result.clusters:
        themes = Counter(theme_for(result.items[i].text) for i in cluster.members)
        theme, count = themes.most_common(1)[0]
        if theme is not None:
            assert count / cluster.size >= 0.6, (method, themes)
            dominant.add(theme)
    assert dominant == {t[0] for t in THEMES}


async def test_dedupe_removes_exact_and_near_duplicates():
    items = feedback()
    unique = exact_dedupe(items)
    assert len(unique) <= len(items) - 5  # at least the 5 planted case-only reposts
    assert not any(i.text.isupper() for i in unique)
    result = await analyze_feedback(items, HashEmbeddings())
    assert result.n_items == len(items) and result.n_after_dedupe <= len(items) - 5


def _regional(f) -> str | None:
    """Region of a per-region finding ("... items in CN"), None for a theme's overall finding."""
    m = re.search(r" items in (\w+)$", f.quantity.qualifier)
    return m.group(1) if m else None


async def test_weights_equal_cluster_shares_and_sum_to_one_minus_noise(analysis_request):
    out = await build_graph().ainvoke({"run_id": "fb", "request": analysis_request})
    report = out["analysis"].reports["feedback"]
    assert report.status == "ok"
    n = report.stats["n_after_dedupe"]
    total = 0.0
    overall = [f for f in report.findings if _regional(f) is None]
    for f in report.findings:
        size, of = map(int, re.match(r"(\d+) of (\d+)", f.quantity.qualifier).groups())
        assert f.weight == pytest.approx(size / of)
        assert (
            f.quantity.value == pytest.approx(f.weight, abs=1e-4)
            and f.quantity.origin == "computed"
        )
        assert all(s.startswith("fb:") for s in f.source_ids)
    for f in overall:
        assert int(f.quantity.qualifier.split(" of ")[1].split()[0]) == n
        total += f.weight
    assert total == pytest.approx(1 - report.stats["noise_share"], abs=1e-3)
    # every planted theme surfaces as an attribute
    assert {f.attribute for f in overall} >= {t[1] for t in THEMES}
    # feedback sources carry the verbatim item text
    texts = {i.item_id: i.text for i in feedback()}
    for s in report.sources:
        assert s.kind == "feedback" and s.excerpt == texts[s.ref]


async def test_cn_only_theme_keeps_its_regional_share(analysis_request):
    report = (await build_graph().ainvoke({"run_id": "fbr", "request": analysis_request}))[
        "analysis"
    ].reports["feedback"]
    items = {i.item_id: i for i in feedback()}
    theme = next(t for t in THEMES if t[0] == CN_ONLY_THEME)
    of_theme = [f for f in report.findings if f.attribute == theme[1]]
    overall = next(f for f in of_theme if _regional(f) is None)
    cn = next(f for f in of_theme if _regional(f) == "CN")
    assert not any(_regional(f) == "EU" for f in of_theme)
    assert cn.weight > 2 * overall.weight  # diluted overall, strong in CN
    assert "CN" in cn.claim and all(items[sid[3:]].market == "CN" for sid in cn.source_ids)
    assert report.stats["region_share:CN"] + report.stats["region_share:EU"] == pytest.approx(
        1, abs=1e-3
    )
    # findings for themes present everywhere exist per region, each citing items from that region only
    for f in report.findings:
        region = _regional(f)
        if region:
            markets = {"EU": {"DE", "FR"}, "CN": {"CN"}}[region]
            assert all(items[sid[3:]].market in markets for sid in f.source_ids)


async def test_single_region_run_has_no_regional_split():
    request = AnalysisRequest(model_code=REF_CODE, regions=["EU"])
    report = (await build_graph().ainvoke({"run_id": "fbeu", "request": request}))[
        "analysis"
    ].reports["feedback"]
    assert report.findings and not any(_regional(f) for f in report.findings)
    assert CN_ONLY_THEME not in {f.attribute for f in report.findings}
    assert report.stats["region_share:EU"] == 1.0
