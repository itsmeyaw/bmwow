"""Import private workbooks; stdout contains aggregate validation counts only."""

import argparse
import json
from datetime import date
from pathlib import Path

from bmwow.knowledge.ingestion import merge_candidate, write_snapshot
from bmwow.knowledge.manifest import initial_manifest, load_manifest
from bmwow.knowledge.repository import FileSnapshotRepository
from bmwow.knowledge.workbooks import WorkbookImporter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--init-config", action="store_true", help="Write a curation template, then exit."
    )
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--report", type=Path, help="Private report containing original unmapped questions."
    )
    parser.add_argument(
        "--catalog-bundle", type=Path, help="Closed, reviewed catalog staging bundle."
    )
    parser.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args()
    if args.init_config:
        args.config.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite a team's curated configuration.
        with args.config.open("x", encoding="utf-8") as handle:
            handle.write(initial_manifest().model_dump_json(indent=2) + "\n")
        print("Curation template created; pending team decisions remain explicit.")
        return 0
    if args.input_dir is None or args.output is None or args.as_of is None:
        parser.error("--input-dir, --output, and --as-of are required for import")
    manifest = load_manifest(args.config)
    importer = WorkbookImporter(manifest, as_of=args.as_of)
    importer.import_sales(args.input_dir / "sales_volumes.xlsx")
    importer.import_studies(args.input_dir / "F70_G60_G68_G70_customer_studies.xlsx")
    bundle, config, report = importer.finish()
    if args.catalog_bundle:
        staging = FileSnapshotRepository(args.catalog_bundle).load_snapshot()
        if any(node.type in {"Requirement", "Decision"} for node in staging.nodes):
            parser.error("Catalog staging must not contain requirements or human Decisions")
        bundle = merge_candidate(bundle, staging)
    write_snapshot(args.output, bundle)
    manifest.knowledge = config
    # Store the resolved config beside its snapshot, preserving the input curation file.
    manifest_path = args.output.with_suffix(".config.json")
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report.model_dump(exclude={"questions"}), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
