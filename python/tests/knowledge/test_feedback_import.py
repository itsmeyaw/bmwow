import csv
import json

import pytest
from openpyxl import Workbook

from bmwow.knowledge.feedback_import import export_feedback_workbook


def make_source(tmp_path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Synthetic feedback"
    sheet.append(["ID", "Customer Feedback", "Derivate (e-code)", "Country", "Feedback Type"])
    for row in rows:
        sheet.append(row)
    path = tmp_path / "synthetic_feedback_hackathon.xlsx"
    workbook.save(path)
    return path


def test_export_preserves_mixed_aspects_whitespace_and_original_locators(tmp_path):
    source = make_source(
        tmp_path,
        [
            ["synthetic-1", "  Invented text, with\nmultiple lines.  ", "G70", "US", "Likes"],
            ["synthetic-1", "  Invented text, with\nmultiple lines.  ", "G70", "US", "Defect"],
            ["synthetic-2", "Identical text can have its own identity.", "G70", "US", None],
        ],
    )
    output = tmp_path / "feedback.csv"
    report = export_feedback_workbook(source, output)
    with output.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert report.rows == 3 and report.distinct_feedback == 2
    assert rows[0]["Customer Feedback"] == "  Invented text, with\nmultiple lines.  "
    assert [r["Feedback Type"] for r in rows] == ["Likes", "Defect", ""]
    origin = json.loads(rows[1]["__bmwow_origin"])
    assert origin["source_hash"] == report.source_hash
    assert origin["locator"] == {
        "kind": "spreadsheet",
        "sheet": "Synthetic feedback",
        "range": "A3:E3",
    }
    first = output.read_bytes()
    export_feedback_workbook(source, output)
    assert output.read_bytes() == first


def test_bad_header_or_uncached_formula_does_not_replace_output(tmp_path):
    source = make_source(tmp_path, [["synthetic-1", "=A2", "G70", "US", "Likes"]])
    output = tmp_path / "feedback.csv"
    output.write_text("previous complete export")
    with pytest.raises(ValueError, match="cached"):
        export_feedback_workbook(source, output)
    assert output.read_text() == "previous complete export"
