"""Validate Neon feedback through v1; output aggregate checks, never Verbatim or credentials."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from bmwow.knowledge import FeedbackFilter, FeedbackKnowledgeService
from bmwow.knowledge.neon import FeedbackStorageError, create_neon_feedback_service
from dotenv import load_dotenv

from src.agent.sources import feedback_source
from src.agent.tools.knowledge import ModuleBackend
from src.knowledge import configure_service, ontology, sql_client
from src.models.evidence import Source


async def inspect_service(
    service: FeedbackKnowledgeService, *, derivate: str, country: str, limit: int
) -> dict:
    configure_service(service)
    backend = ModuleBackend(ontology, sql_client)
    try:
        filters = FeedbackFilter(models=[derivate], markets=[country], limit=limit)
        page = await backend.get_feedback_page(filters)
        assert page is not None
        items = page.items
        models = await backend.list_supported_models()
        regions = await backend.list_regions()
        model = await backend.get_model(derivate)
        has_coverage = model is not None and country in model.regions
        if items:
            assert has_coverage and any(value["model_code"] == derivate for value in models or [])
            assert country in (regions or {}).get(country, {}).get("markets", [])
        assert len({item.references[0].record_key for item in items}) == len(items)
        assert all(item.model == derivate and item.market == country for item in items)
        assert all(item.date is None and item.rating is None for item in items)
        assert page.retrieval.returned_count == len(items)
        citation_checks = 0
        for item in items[:3]:
            source = Source.model_validate_json(feedback_source(item).model_dump_json())
            assert source.aspects == item.aspects and source.retrieval == item.retrieval
            resolved = await backend.resolve_citation(source.id)
            assert resolved is not None and resolved.text == item.text
            assert resolved.references == item.references and resolved.aspects == item.aspects
            citation_checks += 1
            if item.aspects:
                resolved_aspect = await backend.resolve_citation(item.aspects[0].aspect_id)
                assert resolved_aspect == item.aspects[0]
                citation_checks += 1
        aspects = [aspect for item in items for aspect in item.aspects]
        availability = await backend.get_data_availability()
        return {
            "derivate": derivate,
            "country": country,
            "request_has_feedback_coverage": has_coverage,
            "feedback": page.retrieval.model_dump(mode="json"),
            "aspects_in_selection": len(aspects),
            "curated_aspects": sum(a.extraction_source == "vfc_label" for a in aspects),
            "inferred_aspects": sum(a.extraction_source == "llm" for a in aspects),
            "inferred_without_supported_quote": sum(
                a.quote_status in {"missing", "mismatch"} for a in aspects
            ),
            "citation_checks_passed": citation_checks,
            "availability": [value.model_dump(mode="json") for value in availability or []],
            "validation": "passed; no LLM, embedding, or web provider calls",
        }
    finally:
        configure_service(None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Local ignored file holding DATABASE_URL.")
    parser.add_argument("--derivate", default="G70")
    parser.add_argument("--country", default="US")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("limit must be nonnegative")
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("The requested environment file does not exist.")
        load_dotenv(args.env_file, override=False)
    try:
        result = asyncio.run(
            inspect_service(
                create_neon_feedback_service(),
                derivate=args.derivate.strip().upper(),
                country=args.country.strip().upper(),
                limit=args.limit,
            )
        )
    except (FeedbackStorageError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
