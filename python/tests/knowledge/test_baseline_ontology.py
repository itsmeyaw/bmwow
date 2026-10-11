from bmwow.agent.models.evidence import AnalysisRequest
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
