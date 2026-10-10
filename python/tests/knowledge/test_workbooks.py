"""Invented workbook structures exercise source mapping without private records."""

from datetime import date
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from bmwow.knowledge import InMemoryRepository, KnowledgeService, VfcMapping
from bmwow.knowledge.ingestion import merge_candidate
from bmwow.knowledge.manifest import initial_manifest
from bmwow.knowledge.workbooks import WorkbookImporter
from bmwow.ontology import snapshot_fingerprint, validate_bundle
from bmwow.ontology.models import Feature


def workbook(path, sheets):
    """Minimal independent OOXML fixture, read by the production XLSX library."""
    with ZipFile(path, "w") as archive:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + overrides
            + "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        names = "".join(
            f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(sheets, 1)
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + names
            + "</sheets></workbook>",
        )
        relations = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + relations
            + "</Relationships>",
        )
        for i, rows in enumerate(sheets.values(), 1):
            content = []
            for row_index, row in enumerate(rows, 1):
                cells = []
                for column, value in enumerate(row, 1):
                    coordinate = f"{chr(64 + column)}{row_index}"
                    if value is None:
                        continue
                    if isinstance(value, str):
                        cell = (
                            f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                        )
                    elif isinstance(value, tuple):
                        cell = f'<c r="{coordinate}"><f>{escape(value[0])}</f></c>'
                    else:
                        cell = f'<c r="{coordinate}"><v>{value}</v></c>'
                    cells.append(cell)
                content.append(f'<row r="{row_index}">' + "".join(cells) + "</row>")
            archive.writestr(
                f"xl/worksheets/sheet{i}.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                + "".join(content)
                + "</sheetData></worksheet>",
            )


@pytest.fixture
def inputs(tmp_path):
    sales = tmp_path / "sales.xlsx"
    studies = tmp_path / "studies.xlsx"
    sales_rows = [
        ["market", "market_code", "volume_2024", "volume_2025", "volume_2030"],
        ["Invented Europe", "EU", 10, 12, 20],
        ["Invented China", "CN", 0, 0, 0],
        ["Invented US", "US", 5, 6, 7],
        ["Invented rest", "RoW", 1, 2, 3],
    ]
    workbook(sales, {name: sales_rows for name in ("F70", "G60_G68", "G70")})
    workbook(
        studies,
        {
            "CN_EU_2025": [
                [],
                [None, "CN", None, "EU"],
                ["Invented comfort question", "G68", "G70", "F70", "G60", "G70"],
                ["Mean", 3.1, 3.2, 3.3, 3.4, 3.5],
            ],
            "US_2025": [
                ["Invented usability question", None, "G60", "G70"],
                ["Sample total", "% of column, sample base", 1, 1],
                ["Invented easy answer", "% of column, sample base", 0.25, 0.4],
                ["Invented difficult answer", "% of column, sample base", 0.75, 0.6],
            ],
        },
    )
    return sales, studies


def imported(inputs, manifest=None):
    importer = WorkbookImporter(
        manifest or initial_manifest(), as_of=date(2026, 10, 11), origin="synthetic"
    )
    importer.import_sales(inputs[0])
    importer.import_studies(inputs[1])
    return importer.finish()


def test_import_preserves_cells_unknowns_and_combined_sales(inputs):
    bundle, config, report = imported(inputs)
    assert not validate_bundle(bundle)
    assert report.sales_measurements == 36 and report.study_means == 5 and report.study_shares == 4
    assert report.normalized_totals == 2 and report.unmapped_questions == 2
    service = KnowledgeService(InMemoryRepository(bundle), config)
    rows = service.sales_volume(["G60", "G68"], ["EU"])
    assert len(rows) == 3 and all(row.source_group == "G60_G68" for row in rows)
    assert service.sales_volume(["G68"], ["EU"]) == rows
    assert next(row for row in rows if row.period == "2030").status == "source_reported_future"
    assert service.sales_volume(["F70"], ["CN"])[0].units == 0
    assert service.sales_volume(["G60"], ["DE"]) == []
    scores = service.get_study_scores(["G60"], ["US"])
    assert len(scores) == 2 and {score.value for score in scores} == {0.25, 0.75}
    assert {score.response_category for score in scores} == {
        "Invented easy answer",
        "Invented difficult answer",
    }
    assert all(
        score.measurement.sample_size is None and score.measurement.denominator is None
        for score in scores
    )
    assert {score.references[0].locator.range for score in scores} == {"C3", "C4"}
    assert all(score.context.country_codes == [] for score in scores)
    assert "CN" not in service.get_model("G60").data_coverage["customer_study"]
    assert service.get_model("G60").sold_regions == []
    assert len(service.sales_volume(["G60"], ["ROW"])) == 3


def test_import_is_idempotent_and_source_changes_create_new_ids(inputs):
    first, config, _ = imported(inputs)
    second, second_config, _ = imported(inputs)
    assert snapshot_fingerprint(merge_candidate(first, second)) == snapshot_fingerprint(
        merge_candidate(second, first)
    )
    assert len(merge_candidate(first, second).nodes) == len(first.nodes)
    assert config == second_config
    # A different source version cannot overwrite the old source's Evidence.
    with inputs[0].open("ab") as handle:
        handle.write(b"synthetic-version-change")
    third, _, _ = imported(inputs)
    first_sales = {
        node.id
        for node in first.nodes
        if node.type == "Evidence" and node.properties.evidence_kind == "sales_statistic"
    }
    third_sales = {
        node.id
        for node in third.nodes
        if node.type == "Evidence" and node.properties.evidence_kind == "sales_statistic"
    }
    assert first_sales.isdisjoint(third_sales)


@pytest.mark.parametrize("status", ["proposed", "reviewed"])
def test_only_reviewed_question_mappings_create_findings(inputs, status):
    manifest = initial_manifest()
    manifest.context_nodes.append(
        Feature(
            id="feature:invented-comfort",
            entity_key="feature:invented-comfort",
            label="Invented comfort",
            revision=1,
            type="Feature",
            properties={
                "definition": "Invented comfort capability",
                "domains": ["interior"],
                "aliases": [],
            },
        )
    )
    manifest.knowledge.feature_keys["feature:invented-comfort"] = "invented_comfort"
    manifest.knowledge.study_mappings["Invented comfort question"] = VfcMapping(
        feature_id="feature:invented-comfort",
        status=status,
        rationale="Synthetic mapping review",
    )
    bundle, _, report = imported(inputs, manifest)
    signals = [node for node in bundle.nodes if node.type == "Signal"]
    assert len(signals) == (5 if status == "reviewed" else 0)
    assert all(node.properties.sentiment == "not_applicable" for node in signals)
    assert report.unmapped_questions == (1 if status == "reviewed" else 2)


def test_unknown_mapping_target_is_rejected(inputs):
    manifest = initial_manifest()
    manifest.knowledge.study_mappings["Invented comfort question"] = VfcMapping(
        feature_id="feature:absent",
        status="reviewed",
        rationale="Synthetic invalid target",
    )
    with pytest.raises(ValueError, match="validation"):
        imported(inputs, manifest)


@pytest.mark.parametrize(
    "value, error", [(-1, "nonnegative"), (1.5, "nonnegative"), (("1+1",), "cached")]
)
def test_invalid_sales_and_uncached_formulas_do_not_become_zero(inputs, value, error):
    rows = [
        ["market", "market_code", "volume_2024", "volume_2025", "volume_2030"],
        ["Invented US", "US", value, 1, 2],
    ]
    workbook(inputs[0], {name: rows for name in ("F70", "G60_G68", "G70")})
    with pytest.raises(ValueError, match=error):
        imported(inputs)


def test_missing_measurement_is_reported_not_invented(inputs):
    workbook(
        inputs[1],
        {
            "CN_EU_2025": [
                [],
                [None, "CN", None, "EU"],
                ["Invented question", "G68", "G70", "F70", "G60", "G70"],
                ["Mean", None, 2, 3, 4, 5],
            ],
            "US_2025": [
                ["Invented question", None, "G60", "G70"],
                ["Sample total", "% of column, sample base", 1, 1],
                ["Invented answer", "% of column, sample base", 0.5, 0.5],
            ],
        },
    )
    _, _, report = imported(inputs)
    assert report.missing_cells == 1 and report.study_means == 4


def test_changed_region_headers_cannot_silently_rescope_repeated_model_columns(inputs):
    path = inputs[1]
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    name = "xl/worksheets/sheet1.xml"
    entries[name] = entries[name].replace(b">CN<", b">EU<")
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="region headers"):
        imported(inputs)
