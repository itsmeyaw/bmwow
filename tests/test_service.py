import asyncio

import pytest

from src.agent import service
from src.agent.config import get_settings
from src.models.evidence import AGENT_NAMES


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
        assert ("node_start", f"{agent}_agent") in kinds and ("node_finish", f"{agent}_agent") in kinds
    assert kinds.index(("node_finish", "collect")) > max(kinds.index(("node_finish", f"{a}_agent")) for a in AGENT_NAMES)
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
    all_ids = {f.id for r in analysis.reports.values() for f in r.findings} | \
              {s.id for r in analysis.reports.values() for s in r.sources}
    assert exp.cited_ids and set(exp.cited_ids) <= all_ids
    with pytest.raises(KeyError):
        await service.explain(run_id, "?", finding_id="F-baseline-999")
