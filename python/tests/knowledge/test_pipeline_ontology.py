"""The full situation-analysis pipeline against the ontology-backed knowledge service (synthetic
snapshot), with fake LLM and web providers: real nodes, real adapter, real ontology projections."""

from bmwow.agent.models.evidence import AGENT_NAMES, AnalysisRequest, SituationAnalysis
from bmwow.agent.supervisor import build_graph
from bmwow.ontology import validate_bundle


async def test_pipeline_runs_on_the_ontology_and_keeps_it_unchanged(bridge, knowledge_service):
    before = knowledge_service.snapshot().model_dump(mode="json")
    request = AnalysisRequest(model_code="G60", regions=["US"])
    out = await build_graph().ainvoke({"run_id": "ontology-pipeline", "request": request})
    analysis = SituationAnalysis.model_validate_json(out["analysis"].model_dump_json())

    assert set(analysis.reports) == set(AGENT_NAMES)
    assert analysis.brief.reference_model.node_id == "vehicle:bmw-g60"
    # features come from the ontology's taxonomy, never from the fallback yaml keys
    taxonomy = knowledge_service.get_taxonomy()
    ontology_features = {a for attrs in taxonomy.values() for a in attrs}
    for pkg in analysis.evidence_packages:
        assert pkg.attribute in ontology_features or pkg.attribute.startswith("unmapped:")
    assert any(p.attribute in ontology_features for p in analysis.evidence_packages)
    # every ontology citation resolves through the knowledge service
    for report in analysis.reports.values():
        for source in report.sources:
            if source.id.startswith("kg:evidence:") or source.id.startswith("kg:vehicle:"):
                assert knowledge_service.resolve_citation(source.id) is not None
    # missing data is reported per agent instead of failing the run
    for report in analysis.reports.values():
        assert report.status in {"ok", "partial"}, (report.agent, report.errors)
    assert analysis.feature_assessments and all(
        a.guard_status in {"passed", "revised", "flagged", "skipped"}
        for a in analysis.feature_assessments
    )
    # the optional write-back is reported, and reading never mutates the ontology
    assert analysis.ontology_persistence is not None
    assert knowledge_service.snapshot().model_dump(mode="json") == before
    assert not validate_bundle(knowledge_service.snapshot())
