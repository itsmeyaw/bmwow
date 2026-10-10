"""Run one situation analysis from a request JSON file (AnalysisRequest) and print a summary.

    KNOWLEDGE_BACKEND=fake .venv/bin/python -m scripts.run_analysis scripts/example_request.json

`model_code` must be in the model registry (G60, F70, G68; `TEST01`/`TEST02` with the fakes, see
`service.list_models()`). `regions` is optional: omitted = all regions the model has data for.

With real API keys this also records the web cache under data/processed/web_cache/ for offline demos
(OFFLINE_MODE=true replays it).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from src.agent import service
from src.agent.config import get_settings
from src.models.evidence import AnalysisRequest


async def main(path: str) -> None:
    request = AnalysisRequest.model_validate(json.loads(Path(path).read_text()))
    brief = await service.resolve(request)
    print(f"brief: {brief.model_code} {brief.reference_model.name} | {brief.segment} | regions {brief.regions} "
          f"| markets {brief.markets} | competitors {[c.name for c in brief.competitors]}")
    for warning in brief.warnings:
        print(f"  warning: {warning}")
    run_id = await service.start_analysis(request, brief_override=brief)
    async for event in service.stream_analysis(run_id):
        detail = f" {event['status']} ({event['n_findings']} findings)" if "status" in event else ""
        print(f"{event['event']:<13} {event.get('node') or ''}{detail}", flush=True)
    status = await service.get_analysis(run_id)
    if status.analysis is None:
        print(f"run failed: {status.error}")
    else:
        for agent, report in status.analysis.reports.items():
            print(f"\n[{agent}] {report.status}: {report.summary}")
            for err in report.errors:
                print(f"  error: {err}")
        print(f"\nSaved {get_settings().analyses_dir / (run_id + '.json')}")
    await service.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
