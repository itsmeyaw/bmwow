"""Verify the Pydantic contract and the generated cross-language JSON Schema."""

import copy
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from bmwow.ontology import GraphBundle, validate_bundle
from bmwow.ontology.models import SourceDocument
from bmwow.ontology.schema import build_schema, render_contracts

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def bundle():
    return json.loads(
        (ROOT / "contracts/ontology/examples/synthetic.json").read_text(encoding="utf-8")
    )


def node(bundle, node_id):
    return next(n for n in bundle["nodes"] if n["id"] == node_id)


def test_typed_fixture_round_trip(bundle):
    parsed = GraphBundle.model_validate_json(json.dumps(bundle))
    assert isinstance(parsed.as_of, date)
    source = next(n for n in parsed.nodes if n.id == "source:fixture-public")
    assert isinstance(source, SourceDocument)
    assert source.properties.retrieved_at.tzinfo is not None
    assert parsed.model_dump(mode="json") == bundle
    assert validate_bundle(parsed) == []


def test_generated_contract_is_valid_and_current(bundle):
    schema = build_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(bundle)
    for name, expected in render_contracts().items():
        assert (ROOT / "contracts/ontology" / name).read_text(encoding="utf-8") == expected


@pytest.mark.parametrize(
    "case",
    [
        "omitted_nullable",
        "extra_field",
        "string_revision",
        "boolean_revision",
        "duplicate_context_id",
        "empty_domains",
        "invalid_locator",
        "invalid_url_scheme",
        "invalid_url_whitespace",
        "invalid_url_escape",
        "statistic_without_measurement",
        "text_without_excerpt",
        "public_without_context",
        "competitor_without_capability",
        "naive_timestamp",
        "invalid_calendar_date",
        "unknown_node_type",
        "blank_explanation",
    ],
)
def test_structural_failures_agree_in_python_and_json_schema(bundle, case):
    source = node(bundle, "source:fixture-public")["properties"]
    evidence = node(bundle, "evidence:fixture-customer")["properties"]
    customer = node(bundle, "signal:fixture-customer")
    match case:
        case "omitted_nullable":
            del source["publisher"]
        case "extra_field":
            customer["properties"]["importance"] = 99
        case "string_revision":
            customer["revision"] = "1"
        case "boolean_revision":
            customer["revision"] = True
        case "duplicate_context_id":
            customer["properties"]["context"]["market_ids"] *= 2
        case "empty_domains":
            next(n for n in bundle["nodes"] if n["type"] == "Feature")["properties"]["domains"] = []
        case "invalid_locator":
            evidence["locator"] = {"kind": "pdf", "page": 0, "section": None}
        case "invalid_url_scheme":
            source["location"]["url"] = "ftp://example.invalid/source"
        case "invalid_url_whitespace":
            source["location"]["url"] = "https://example.invalid/a b"
        case "invalid_url_escape":
            source["location"]["url"] = "https://example.invalid/%GG"
        case "statistic_without_measurement":
            evidence["evidence_kind"] = "study_statistic"
        case "text_without_excerpt":
            evidence["raw_text"] = None
        case "public_without_context":
            node(bundle, "signal:fixture-public-positive")["properties"]["public_context"] = None
        case "competitor_without_capability":
            node(bundle, "signal:fixture-competitor")["properties"]["capability"] = None
        case "naive_timestamp":
            source["retrieved_at"] = "2026-10-10T15:47:12"
        case "invalid_calendar_date":
            bundle["as_of"] = "2026-02-30"
        case "unknown_node_type":
            customer["type"] = "Opinion"
        case "blank_explanation":
            bundle["edges"][0]["rationale"] = " \n\t "

    with pytest.raises(ValidationError):
        GraphBundle.model_validate_json(json.dumps(bundle))
    assert validate_bundle(bundle)
    assert list(
        Draft202012Validator(build_schema(), format_checker=FormatChecker()).iter_errors(bundle)
    )


def test_validation_errors_do_not_include_source_text(bundle):
    evidence = node(bundle, "evidence:fixture-customer")["properties"]
    private_text = "PRIVATE CUSTOMER TEXT THAT MUST NOT APPEAR IN ERRORS"
    evidence["raw_text"] = {"private": private_text}
    errors = validate_bundle(bundle)
    assert errors
    assert private_text not in "\n".join(errors)


@pytest.mark.parametrize("typed", [False, True])
def test_non_json_numbers_are_rejected(bundle, typed):
    parsed = GraphBundle.model_validate_json(json.dumps(bundle)) if typed else None
    criterion = node(bundle, "requirement:fixture-parking")["properties"]["acceptance_criteria"][0]
    criterion["target"] = float("nan")
    if typed:
        requirement = next(n for n in parsed.nodes if n.id == "requirement:fixture-parking")
        requirement.properties.acceptance_criteria[0].target = float("nan")
    assert validate_bundle(parsed if typed else bundle) == [
        "schema/: input must be a finite JSON object"
    ]


def test_model_instances_are_revalidated_before_graph_checks(bundle):
    parsed = GraphBundle.model_validate_json(json.dumps(bundle))
    parsed.nodes[0].revision = 0
    assert any("schema/" in error for error in validate_bundle(parsed))


def test_schema_cli_generates_and_detects_drift(tmp_path):
    command = [str(Path(sys.executable).with_name("bmwow-schema")), "--output-dir", str(tmp_path)]
    generated = subprocess.run(command, capture_output=True, text=True, check=False)
    assert generated.returncode == 0, generated.stderr
    current = subprocess.run([*command, "--check"], capture_output=True, text=True, check=False)
    assert current.returncode == 0, current.stdout + current.stderr
    (tmp_path / "schema.json").write_text("{}\n", encoding="utf-8")
    stale = subprocess.run([*command, "--check"], capture_output=True, text=True, check=False)
    assert stale.returncode == 1
    assert "STALE" in stale.stdout


def test_validation_cli_reports_valid_and_invalid_bundles(bundle, tmp_path):
    command = [str(Path(sys.executable).with_name("bmwow-validate"))]
    valid = subprocess.run(
        [*command, str(ROOT / "contracts/ontology/examples/synthetic.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stdout + valid.stderr
    invalid_bundle = copy.deepcopy(bundle)
    invalid_bundle["edges"][0]["target_id"] = "source:missing"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid_bundle), encoding="utf-8")
    invalid = subprocess.run([*command, str(path)], capture_output=True, text=True, check=False)
    assert invalid.returncode == 1
    assert "dangling relationship" in invalid.stdout
