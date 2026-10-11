import json

from bmwow.agent.config import get_settings
from bmwow.agent.models.evidence import AnalysisRequest
from bmwow.agent.taxonomy import load_taxonomy
from tests.test_baseline import run_baseline


async def test_study_scores_from_the_ontology_are_cited_and_resolve(bridge, knowledge_service):
    report = await run_baseline(AnalysisRequest(model_code="G60", regions=["US"]))
    studies = [f for f in report.findings if f.quantity and "study" in f.claim.lower()]
    assert studies, report.findings
    sources = {s.id: s for s in report.sources}
    for f in studies:
        assert f.region == "US" and f.quantity.origin == "record"
        (sid,) = f.source_ids
        assert sources[sid].measurement is not None
        assert knowledge_service.resolve_citation(sid) is not None


async def test_categorical_study_answers_collapse_to_one_finding_with_curated_feature(
    bridge, knowledge_service, monkeypatch, tmp_path
):
    (base,) = knowledge_service.get_study_scores(["G60"], ["US"])[:1]
    rows = [("I Hate It", 0.1, "C75"), ("Excellent", 0.3, "C79"), ("I Love It", 0.6, "C81")]
    scores = []
    for category, value, cell in rows:
        ref = base.references[0]
        ref = ref.model_copy(update={"locator": ref.locator.model_copy(update={"range": cell})})
        scores.append(
            base.model_copy(
                update={
                    "node_id": f"{base.node_id}-{cell}",
                    "question": "Phone charging",
                    "statistic": "proportion",
                    "response_category": category,
                    "value": value,
                    "references": [ref],
                }
            )
        )
    monkeypatch.setattr(knowledge_service, "get_study_scores", lambda models, regions: scores)
    feature = next(iter((await load_taxonomy()).area_of))  # any feature the taxonomy offers
    curation = tmp_path / "knowledge" / "curation.json"
    curation.parent.mkdir()
    curation.write_text(
        json.dumps(
            {
                "knowledge": {
                    "feature_keys": {"feature:x": feature},
                    "study_mappings": {
                        "Phone charging": {
                            "feature_id": "feature:x",
                            "status": "proposed",
                            "rationale": "x",
                        }
                    },
                }
            }
        )
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("bmwow.agent.nodes.baseline.feature_for_term", lambda term: "unrelated")
    report = await run_baseline(AnalysisRequest(model_code="G60", regions=["US"]))
    (finding,) = [f for f in report.findings if "Phone charging" in f.claim]
    assert finding.quantity.value == 0.9 and finding.quantity.origin == "computed"
    assert "'Excellent' + 'I Love It'" in finding.claim and "I Hate It 10.0%" in finding.claim
    assert len(finding.source_ids) == 3
    # the curated mapping wins over the word alias and is labeled with its review status
    assert finding.attribute == feature and "mapping proposed" in finding.quantity.qualifier


async def test_sales_are_asked_at_region_grain_too(bridge, knowledge_service, monkeypatch):
    asked = []
    sales_volume = knowledge_service.sales_volume

    def spy(models, markets=None, *args, **kwargs):
        asked.append(markets)
        return sales_volume(models, markets, *args, **kwargs)

    monkeypatch.setattr(knowledge_service, "sales_volume", spy)
    report = await run_baseline(AnalysisRequest(model_code="G60", regions=["US"]))
    assert asked and "US" in asked[0]
    assert any("12400 units for US" in f.claim for f in report.findings)
