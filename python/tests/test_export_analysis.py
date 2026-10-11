import re

from bmwow.agent.supervisor import build_graph
from scripts.export_analysis import MIGRATION, rows_of


async def test_every_row_matches_its_table_columns(analysis_request, tmp_path):
    analysis = (await build_graph().ainvoke({"run_id": "export", "request": analysis_request}))[
        "analysis"
    ]
    rows = rows_of(analysis, data_dir=tmp_path)
    ddl = MIGRATION.read_text()
    for table, items in rows.items():
        block = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", ddl, re.S)
        assert block, table
        columns = {
            line.split()[0]
            for line in block.group(1).splitlines()
            if line.strip() and not line.strip().startswith("PRIMARY KEY")
        }
        for row in items:
            assert set(row) <= columns, (table, set(row) - columns)
            assert row["run_id"] == "export"
    assert len(rows["analysis_runs"]) == 1
    assert {f["attribute"] for f in rows["analysis_features"]} == {
        p.attribute for p in analysis.evidence_packages
    }
    finding_ids = {f["finding_id"] for f in rows["analysis_findings"]}
    source_ids = {s["source_id"] for s in rows["analysis_sources"]}
    for link in rows["analysis_finding_sources"]:
        assert link["finding_id"] in finding_ids and link["source_id"] in source_ids
