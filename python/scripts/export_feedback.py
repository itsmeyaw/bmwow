"""Export original feedback workbooks with per-row provenance; aggregate stdout only."""

import argparse
import json
from pathlib import Path

from bmwow.knowledge.feedback_import import export_feedback_directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    reports = export_feedback_directory(args.input_dir, args.output_dir)
    print(json.dumps({"sources": len(reports), "rows": sum(r.rows for r in reports)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
