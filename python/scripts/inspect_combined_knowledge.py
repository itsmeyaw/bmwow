"""Resolve and inspect combined reads without LLM, embedding, or web calls. Aggregate stdout only."""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import dotenv_values

from bmwow.agent.knowledge_bridge import configure_service, ontology, sql_client
from bmwow.agent.models.evidence import AnalysisRequest
from bmwow.agent.resolve import resolve_request
from bmwow.agent.tools.knowledge import ModuleBackend, get_backend, set_backend
from bmwow.knowledge import CombinedKnowledgeService, FeedbackFilter, create_knowledge_service


async def inspect(
    service: CombinedKnowledgeService, model: str, region: str
) -> dict[str, bool | int]:
    old_backend = get_backend()
    configure_service(service)
    set_backend(ModuleBackend(ontology, sql_client))
    try:
        brief = await resolve_request(AnalysisRequest(model_code=model, regions=[region]))
        page = service.get_feedback_page(FeedbackFilter(models=[model], markets=[region], limit=20))
        for item in page.items:
            for ref in item.references:
                assert service.resolve_citation(ref.evidence_id).item_id == item.item_id
        sales = service.sales_volume([model], [region])
        studies = service.get_study_scores([model], [region])
        for row in [*sales, *studies]:
            for ref in row.references:
                assert service.resolve_citation(ref.evidence_id).id == ref.evidence_id
        return {
            "resolved": True,
            "segment_reviewed": brief.segment != "unknown",
            "feedback_matching": page.retrieval.total_matching,
            "feedback_returned": len(page.items),
            "sales_rows": len(sales),
            "study_measurements": len(studies),
            "citations_resolved": True,
        }
    finally:
        configure_service(None)
        set_backend(old_backend)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--model", default="G60")
    parser.add_argument("--region", default="EU")
    args = parser.parse_args()
    # Read only DATABASE_URL, without loading provider keys into the process.
    database_url = dotenv_values(args.env_file).get("DATABASE_URL")
    service = create_knowledge_service(args.snapshot, args.config, database_url=database_url)
    print(json.dumps(asyncio.run(inspect(service, args.model, args.region)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
