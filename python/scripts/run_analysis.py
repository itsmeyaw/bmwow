"""Run one situation analysis from a request JSON file (AnalysisRequest) and print a summary.

    KNOWLEDGE_BACKEND=fake .venv/bin/python -m scripts.run_analysis scripts/example_request.json

`model_code` must be in the model registry (G60, F70, G68; `TEST01`/`TEST02` with the fakes, see
`service.list_models()`). `regions` is optional: omitted = all regions the model has data for.

With real API keys this also records the web cache under data/processed/web_cache/ for offline demos
(OFFLINE_MODE=true replays it).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import dotenv_values

from bmwow.agent import service
from bmwow.agent.config import get_settings
from bmwow.agent.knowledge_bridge import configure_service, ontology, sql_client
from bmwow.agent.models.evidence import AnalysisRequest
from bmwow.agent.tools.knowledge import ModuleBackend, set_backend
from bmwow.knowledge import create_knowledge_service


async def main(path: str, *, resolve_only: bool = False) -> None:
    request = AnalysisRequest.model_validate(json.loads(Path(path).read_text()))
    brief = await service.resolve(request)
    print(
        f"brief: {brief.model_code} {brief.reference_model.name} | {brief.segment} | regions {brief.regions} "
        f"| markets {brief.markets} | competitors {[c.name for c in brief.competitors]}"
    )
    for warning in brief.warnings:
        print(f"  warning: {warning}")
    if resolve_only:
        await service.aclose()
        return
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--knowledge-config", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--resolve-only", action="store_true", help="Resolve the brief without provider calls."
    )
    args = parser.parse_args()
    if bool(args.snapshot) != bool(args.knowledge_config):
        parser.error("--snapshot and --knowledge-config must be supplied together")
    if args.snapshot:
        database_url = (
            dotenv_values(args.env_file).get("DATABASE_URL")
            if args.env_file
            else os.getenv("DATABASE_URL")
        )
        configure_service(
            create_knowledge_service(
                args.snapshot, args.knowledge_config, database_url=database_url
            )
        )
        set_backend(ModuleBackend(ontology, sql_client))
    asyncio.run(main(args.request, resolve_only=args.resolve_only))
