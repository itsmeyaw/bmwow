"""Inspect the data boundary with aggregate stdout and no agent or provider imports."""

import argparse
from pathlib import Path

from dotenv import dotenv_values

from bmwow.knowledge.factory import create_knowledge_service
from bmwow.knowledge.readiness import inspect_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--model", default="G70")
    parser.add_argument("--region", default="US")
    parser.add_argument("--feature", action="append", default=[])
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--sales-region")
    parser.add_argument("--study-region")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    service = create_knowledge_service(
        args.snapshot, args.config, database_url=dotenv_values(args.env_file).get("DATABASE_URL")
    )
    report = inspect_readiness(
        service,
        model=args.model,
        region=args.region,
        feature_keys=args.feature,
        limit=args.limit,
        sales_region=args.sales_region,
        study_region=args.study_region,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(report.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
