import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.agent import service, supervisor
from src.agent.config import get_settings
from src.agent.tools import knowledge
from src.models.evidence import AGENT_NAMES, OntologyPersistence, SituationAnalysis


@pytest.fixture(autouse=True)
async def close_service():
    yield
    await service.aclose()


async def _finish(run_id: str) -> service.RunStatus:
    for _ in range(200):
        status = await service.get_analysis(run_id)
        if status.state != "running":
            return status
        await asyncio.sleep(0.05)
    raise AssertionError("run did not finish")


async def test_start_get_stream(analysis_request):
    run_id = await service.start_analysis(analysis_request)
    events = [e async for e in service.stream_analysis(run_id)]
    status = await _finish(run_id)
    assert status.state == "done" and status.analysis is not None
    assert status.agents == {a: "ok" for a in AGENT_NAMES}
    kinds = [(e["event"], e.get("node")) for e in events]
    assert kinds[0] == ("run_started", None) and kinds[-1] == ("run_finished", None)
    for agent in AGENT_NAMES:
        assert ("node_start", f"{agent}_agent") in kinds and (
            "node_finish",
            f"{agent}_agent",
        ) in kinds
    assert kinds.index(("node_finish", "collect")) > max(
        kinds.index(("node_finish", f"{a}_agent")) for a in AGENT_NAMES
    )
    assert get_settings().checkpoint_db.exists()
    # a late subscriber gets the full replay
    assert [e async for e in service.stream_analysis(run_id)] == events


async def test_get_analysis_survives_restart(analysis_request):
    run_id = await service.start_analysis(analysis_request)
    await _finish(run_id)
    service._runs.clear()
    status = await service.get_analysis(run_id)
    assert status.state == "done" and status.analysis.run_id == run_id
    with pytest.raises(KeyError):
        await service.get_analysis("nope")


@pytest.mark.parametrize("outcome_status", ["skipped", "stored", "failed"])
async def test_ontology_persistence_is_saved_exposed_and_recovered(
    outcome_status, analysis_request, monkeypatch
):
    ontology = knowledge.get_backend().ontology
    original_store = ontology.store_findings
    if outcome_status == "skipped":
        monkeypatch.delattr(ontology, "store_findings")
    else:

        def store_findings(analysis):
            # The optional write cannot prevent recovery of the local analysis.
            path = get_settings().analyses_dir / f"{analysis.run_id}.json"
            saved = SituationAnalysis.model_validate_json(path.read_text())
            assert saved.run_id == analysis.run_id and saved.reports
            if outcome_status == "failed":
                raise RuntimeError("synthetic storage failure")
            original_store(analysis)

        monkeypatch.setattr(ontology, "store_findings", store_findings)

    run_id = await service.start_analysis(analysis_request)
    events = [event async for event in service.stream_analysis(run_id)]
    status = await _finish(run_id)
    expected = OntologyPersistence(
        status=outcome_status,
        error="RuntimeError: synthetic storage failure" if outcome_status == "failed" else None,
    )
    assert status.state == "done" and status.error is None
    assert status.agents == {a: "ok" for a in AGENT_NAMES}
    assert status.ontology_persistence == status.analysis.ontology_persistence == expected
    assert any(report.findings for report in status.analysis.reports.values())
    assert events[-1]["event"] == "run_finished"
    assert events[-1]["ontology_persistence"] == expected.model_dump(mode="json")
    path = get_settings().analyses_dir / f"{run_id}.json"
    assert SituationAnalysis.model_validate_json(path.read_text()) == status.analysis

    service._runs.clear()
    restored = await service.get_analysis(run_id)
    assert restored.state == "done" and restored.ontology_persistence == expected
    assert restored.analysis == status.analysis
    restored_events = [event async for event in service.stream_analysis(run_id)]
    assert restored_events == [
        {
            "run_id": run_id,
            "event": "run_finished",
            "ontology_persistence": expected.model_dump(mode="json"),
        }
    ]


async def test_legacy_analysis_has_unknown_ontology_persistence(analysis_request):
    run_id = await service.start_analysis(analysis_request)
    await _finish(run_id)
    path = get_settings().analyses_dir / f"{run_id}.json"
    payload = json.loads(path.read_text())
    del payload["ontology_persistence"]
    path.write_text(json.dumps(payload))
    service._runs.clear()

    status = await service.get_analysis(run_id)
    assert status.state == "done"
    assert status.ontology_persistence is status.analysis.ontology_persistence is None
    events = [event async for event in service.stream_analysis(run_id)]
    assert events == [{"run_id": run_id, "event": "run_finished", "ontology_persistence": None}]


async def test_local_save_failure_propagates_before_ontology_write(analysis_request, monkeypatch):
    brief = await service.resolve(analysis_request)
    store = AsyncMock(return_value=True)
    monkeypatch.setattr(knowledge.get_backend(), "store_findings", store)

    def fail_save(*args, **kwargs):
        raise OSError("synthetic local save failure")

    monkeypatch.setattr(Path, "write_text", fail_save)
    with pytest.raises(OSError, match="synthetic local save failure"):
        await supervisor.collect(
            {"run_id": "local-failure", "request": analysis_request, "brief": brief, "reports": {}}
        )
    store.assert_not_awaited()


async def test_outcome_update_failure_keeps_recoverable_analysis(analysis_request, monkeypatch):
    brief = await service.resolve(analysis_request)
    store = AsyncMock(return_value=True)
    monkeypatch.setattr(knowledge.get_backend(), "store_findings", store)

    def fail_replace(*args, **kwargs):
        raise OSError("synthetic outcome update failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic outcome update failure"):
        await supervisor.collect(
            {
                "run_id": "outcome-failure",
                "request": analysis_request,
                "brief": brief,
                "reports": {},
            }
        )
    store.assert_awaited_once()
    path = get_settings().analyses_dir / "outcome-failure.json"
    saved = SituationAnalysis.model_validate_json(path.read_text())
    assert saved.run_id == "outcome-failure" and set(saved.reports) == set(AGENT_NAMES)
    assert saved.ontology_persistence is None
    assert list(path.parent.iterdir()) == [path]


async def test_explain_cites_only_target_evidence(analysis_request):
    run_id = await service.start_analysis(analysis_request)
    analysis = (await _finish(run_id)).analysis
    target = analysis.reports["feedback"].findings[0]
    exp = await service.explain(run_id, "Why does this matter?", finding_id=target.id)
    assert exp.cited_ids and set(exp.cited_ids) <= {target.id, *target.source_ids}
    assert "F-other-999" not in exp.answer and "123456789" not in exp.answer
    assert target.claim.rstrip(".") in exp.answer


async def test_explain_without_target_retrieves_and_validates(analysis_request):
    run_id = await service.start_analysis(analysis_request)
    analysis = (await _finish(run_id)).analysis
    exp = await service.explain(run_id, "What do customers say about seat ventilation?")
    all_ids = {f.id for r in analysis.reports.values() for f in r.findings} | {
        s.id for r in analysis.reports.values() for s in r.sources
    }
    assert exp.cited_ids and set(exp.cited_ids) <= all_ids
    with pytest.raises(KeyError):
        await service.explain(run_id, "?", finding_id="F-baseline-999")
