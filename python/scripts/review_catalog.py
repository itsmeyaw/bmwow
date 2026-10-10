"""Prepare private PDF review candidates or stage explicitly reviewed catalog claims."""

import argparse
import json
from datetime import date
from pathlib import Path

from bmwow.knowledge.catalog import CatalogReview, prepare_catalog, stage_catalog
from bmwow.knowledge.ingestion import write_snapshot
from bmwow.knowledge.manifest import load_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--theme", default=r"seat|sitz|comfort|komfort")
    stage = commands.add_parser("stage")
    stage.add_argument("--review", type=Path, required=True)
    stage.add_argument("--config", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True)
    stage.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        review = prepare_catalog(args.source, theme=args.theme)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(review.model_dump_json(indent=2) + "\n")
        print(json.dumps({"pages": review.pages, "proposed_claims": len(review.claims)}))
    else:
        review = CatalogReview.model_validate_json(args.review.read_text(encoding="utf-8"))
        bundle = stage_catalog(review, load_manifest(args.config), as_of=args.as_of)
        write_snapshot(args.output, bundle)
        print(
            json.dumps(
                {
                    "validated": True,
                    "reviewed_claims": sum(c.status == "reviewed" for c in review.claims),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
