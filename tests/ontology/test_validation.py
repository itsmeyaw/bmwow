"""Contract tests for meaningful provenance, scope, metric, and review failures."""

import copy
import json
import unittest
from pathlib import Path

from bmwow.ontology import validate_bundle

ROOT = Path(__file__).resolve().parents[2] / "contracts/ontology"


class OntologyContractTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((ROOT / "examples/synthetic.json").read_text())

    def node(self, node_id):
        return next(n for n in self.bundle["nodes"] if n["id"] == node_id)

    def assert_invalid(self, text):
        errors = validate_bundle(self.bundle)
        self.assertTrue(errors)
        self.assertTrue(any(text in error for error in errors), errors)

    def test_synthetic_fixture_is_valid(self):
        self.assertEqual(validate_bundle(self.bundle), [])

    def test_dangling_source_is_rejected(self):
        self.bundle["nodes"] = [
            n for n in self.bundle["nodes"] if n["id"] != "source:fixture-feedback"
        ]
        self.assert_invalid("dangling relationship")

    def test_requirement_needs_justification(self):
        self.bundle["edges"] = [e for e in self.bundle["edges"] if e["type"] != "JUSTIFIED_BY"]
        self.assert_invalid("traceable justifications")

    def test_signal_needs_original_evidence(self):
        self.bundle["edges"] = [
            e
            for e in self.bundle["edges"]
            if not (e["type"] == "DERIVED_FROM" and e["source_id"] == "signal:fixture-customer")
        ]
        self.assert_invalid("missing or cyclic evidence chain")

    def test_forward_requirement_needs_assumption(self):
        self.bundle["edges"] = [
            e
            for e in self.bundle["edges"]
            if not (e["type"] == "DEPENDS_ON" and e["source_id"] == "requirement:fixture-parking")
        ]
        self.assert_invalid("forward-looking Assumption")

    def test_cross_model_inference_needs_explanation(self):
        for edge in self.bundle["edges"]:
            if edge["type"] == "JUSTIFIED_BY" and edge["target_id"] == "signal:fixture-competitor":
                edge["context_transfer"] = None
        self.assert_invalid("scope transfer")

    def test_duplicate_feedback_record_is_rejected(self):
        duplicate = copy.deepcopy(self.node("evidence:fixture-customer"))
        duplicate["id"] = "evidence:duplicate"
        duplicate["entity_key"] = "evidence:duplicate"
        self.bundle["nodes"].append(duplicate)
        self.assert_invalid("duplicate Evidence dedup_key")

    def test_software_decision_actor_is_rejected(self):
        self.node("decision:fixture-comment")["properties"]["actor_type"] = "software"
        self.assert_invalid("schema/")

    def test_new_requirement_revision_does_not_inherit_review(self):
        self.node("requirement:fixture-parking")["revision"] = 2
        self.assert_invalid("wrong requirement revision")

    def test_evidence_supported_target_needs_source(self):
        criterion = self.node("requirement:fixture-parking")["properties"]["acceptance_criteria"][0]
        criterion["basis"] = "evidence_supported_target"
        self.assert_invalid("evidence-supported target")

    def test_synthetic_sources_cannot_enter_production(self):
        self.bundle["purpose"] = "production"
        self.assert_invalid("synthetic sources")

    def test_priority_requires_explicit_priority_value(self):
        self.node("decision:fixture-comment")["properties"]["action"] = "set_priority"
        self.assert_invalid("priority is required")

    def test_future_value_is_not_historical(self):
        evidence = self.node("evidence:fixture-customer")["properties"]
        evidence["measurement"] = dict(
            metric="sales_volume",
            value=100,
            value_range=None,
            unit="vehicles",
            statistic="count",
            temporal_status="historical",
            period=dict(label="2030", start=None, end=None),
            sample_size=None,
            denominator=None,
            scale=None,
            comparison_basis=None,
            population=None,
            test_standard=None,
            conditions=[],
            question=None,
            response_category=None,
            notes=[],
        )
        self.assert_invalid("future measurements cannot be historical")

    def test_proportion_bounds(self):
        evidence = self.node("evidence:fixture-customer")["properties"]
        evidence["measurement"] = dict(
            metric="response_share",
            value=1.5,
            value_range=None,
            unit="proportion",
            statistic="proportion",
            temporal_status="historical",
            period=None,
            sample_size=None,
            denominator=None,
            scale=None,
            comparison_basis=None,
            population=None,
            test_standard=None,
            conditions=[],
            question=None,
            response_category=None,
            notes=[],
        )
        self.assert_invalid("proportion must be")

    def test_invalid_relationship_types(self):
        edge = next(e for e in self.bundle["edges"] if e["type"] == "REVIEWS")
        edge["target_id"] = "source:fixture-feedback"
        self.assert_invalid("invalid Decision -> SourceDocument")

    def test_invalid_publication_date(self):
        self.node("source:fixture-public")["properties"]["publication_date"] = "2026-02-30"
        self.assert_invalid("invalid publication date")

    def test_supersedes_cannot_change_logical_entity(self):
        self.bundle["edges"].append(
            dict(
                id="edge:invalid-revision",
                type="SUPERSEDES",
                source_id="requirement:fixture-parking",
                target_id="need:fixture-usability",
                rationale="Invalid revision relationship.",
                context_transfer=None,
            )
        )
        self.assert_invalid("SUPERSEDES must preserve")


if __name__ == "__main__":
    unittest.main()
