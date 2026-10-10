"""Exercise the explicitly synthetic knowledge layer through orchestration v1's bridge."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from bmwow.knowledge import FeedbackFilter, create_synthetic_service
from bmwow.ontology import GraphBundle

from src.agent.tools.knowledge import ModuleBackend
from src.knowledge import configure_service, ontology, sql_client


async def inspect() -> dict:
    fixture = Path(__file__).resolve().parents[1] / "contracts/ontology/examples/synthetic.json"
    service = create_synthetic_service(GraphBundle.model_validate_json(fixture.read_text()))
    configure_service(service)
    backend = ModuleBackend(ontology, sql_client)
    try:
        model = await backend.get_model("G60")
        attributes = await backend.get_attribute_values("vehicle:bmw-g60-fixture-ev")
        feedback = await backend.get_feedback_items(FeedbackFilter(models=["G60"], markets=["US"]))
        sales = await backend.sales_volume(["G60", "G68"], ["US"])
        studies = await backend.get_study_scores(["G60"], ["US"])
        documents = await backend.search_documents("parking", ["study"], ["US"])
        return {
            "dataset": "wholly synthetic",
            "models": await backend.list_supported_models(),
            "model": model.model_dump(mode="json"),
            "attributes": [record.model_dump(mode="json") for record in attributes],
            "feedback": [record.model_dump(mode="json") for record in feedback],
            "sales": [record.model_dump(mode="json") for record in sales],
            "studies": [record.model_dump(mode="json") for record in studies],
            "documents": [record.model_dump(mode="json") for record in documents],
        }
    finally:
        configure_service(None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(inspect())
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print("Synthetic knowledge → orchestration v1 (no Neon, BMW input, or model calls)")
    print("Supported models:", ", ".join(model["model_code"] for model in result["models"]))
    print(f"Feedback records: {len(result['feedback'])}; study scores: {len(result['studies'])}")
    for attribute in result["attributes"]:
        print(
            f"Capability: {attribute['attribute']} = {attribute['value']} {attribute['unit'] or ''}; "
            f"{attribute['availability']}; originals={len(attribute['references'])}"
        )
    for row in result["sales"]:
        print(
            f"Sales: {row['source_group']} / {row['market']} / {row['period']} = {row['units']}; "
            f"{row['status']}; one unsplit observation"
        )


if __name__ == "__main__":
    main()
