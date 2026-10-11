"""Create an ignored offline review form with locally embedded original PDF pages."""

import argparse
import json
from pathlib import Path

from bmwow.knowledge.catalog import CatalogReview
from bmwow.knowledge.local_review import render_local_review
from bmwow.knowledge.manifest import load_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--catalog-review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = load_manifest(args.config)
    catalog = CatalogReview.model_validate_json(args.catalog_review.read_text(encoding="utf-8"))
    rendered = render_local_review(manifest, catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
    print(
        json.dumps({"created": True, "network_calls": 0, "catalog_candidates": len(catalog.claims)})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
