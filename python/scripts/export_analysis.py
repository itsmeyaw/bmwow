"""Export a saved pipeline run to the analysis_* tables in Postgres (Neon), for SQL readers and LLMs.

    uv run python -m scripts.export_analysis ../data/processed/analyses/<run_id>.json           # dry run
    uv run python -m scripts.export_analysis ../data/processed/analyses/<run_id>.json --write   # write

Writes only the analysis_* tables (migrations/0002_analysis.sql, applied idempotently in the same
transaction); never touches feedback or sales tables. A re-export replaces that run's rows. Uses
DATABASE_URL. Without --write it prints the row counts it would write and touches nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

from bmwow.agent.models.evidence import SituationAnalysis, Source
from bmwow.agent.structure import label_of

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "0002_analysis.sql"
TAXONOMY = Path(__file__).resolve().parents[1] / "bmwow" / "agent" / "taxonomy.yaml"

Row = dict[str, Any]
EXCERPT_CHARS = 600  # keeps the stored excerpt readable while saving shared database space


def _area_of() -> dict[str, str]:
    return {
        key: area
        for area, keys in (yaml.safe_load(TAXONOMY.read_text()) or {}).items()
        for key in keys
    }


def _source_type(s: Source) -> str:
    if s.kind == "feedback":
        return "customer_feedback"
    if s.kind == "web":
        return "web_page"
    m = s.measurement
    if m is not None and m.question:
        return "customer_study"
    if m is not None and m.metric == "sales_volume":
        return "sales_dataset"
    if "catalog" in s.ref:
        return "product_catalog"
    return "model_record" if s.ref.startswith("vehicle:") else s.kind


def _fingerprint(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else None


def _code_version() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
        return out.stdout.strip() or None
    except OSError:
        return None


def rows_of(a: SituationAnalysis, data_dir: Path | None = None) -> dict[str, list[Row]]:
    """All rows of one run, per table (pure; no database access)."""
    area_of = _area_of()
    run = a.run_id
    brief = a.brief
    data = data_dir or ROOT / "data"
    inputs = {
        "knowledge_snapshot": _fingerprint(data / "knowledge" / "snapshot.json"),
        "curation": _fingerprint(data / "knowledge" / "curation.json"),
        "web_corpus_manifest": _fingerprint(data / "web_corpus" / "manifest.json"),
        "rules": _fingerprint(
            Path(__file__).resolve().parents[1] / "bmwow" / "agent" / "rules.yaml"
        ),
    }
    out: dict[str, list[Row]] = {
        "analysis_runs": [
            {
                "run_id": run,
                "model_code": brief.model_code,
                "model_name": brief.reference_model.name,
                "segment": brief.segment,
                "regions": list(brief.regions),
                "created_at": a.created_at,
                "llm_model": os.environ.get("LLM_STRONG") or None,
                "code_version": _code_version(),
                "inputs": json.dumps(inputs),
                "agent_status": json.dumps(
                    {
                        name: {
                            "status": r.status,
                            "unavailable": [
                                f"{x.source}: {x.status} {x.reason}".strip()
                                for x in r.availability
                                if x.status != "ok"
                            ],
                            "errors": r.errors[:10],
                        }
                        for name, r in a.reports.items()
                    }
                ),
                "notes": [e for r in a.reports.values() for e in r.errors[:3]],
            }
        ]
    }
    assessments = {x.attribute: x for x in a.feature_assessments}
    features, signals, values, quotes, themes, trends = [], [], [], [], [], []
    for rank, p in enumerate(a.evidence_packages, 1):
        x = assessments.get(p.attribute)
        features.append(
            {
                "run_id": run,
                "attribute": p.attribute,
                "label": p.label or label_of(p.attribute),
                "area": area_of.get(p.attribute, "unmapped"),
                "rank": rank,
                "importance": p.importance,
                "assessment": x.assessment if x else "not_assessed",
                "method": x.method if x else "rule",
                "certainty": x.certainty if x else None,
                "widespread": x.widespread if x else None,
                "what_exactly": x.what_exactly if x else None,
                "reasoning": x.reasoning if x else None,
                "rule_suggestion": x.rule_suggestion if x else None,
                "guard_status": x.guard_status if x else None,
                "brand_or_safety_relevant": x.brand_or_safety_relevant if x else None,
                "cited_ids": list(x.cited_ids) if x else [],
                "guard": json.dumps([g.model_dump() for g in x.guard if not g.ok]) if x else "[]",
                "facts": list(p.comparisons),
                "coverage": list(p.coverage),
                "is_mapped": not p.attribute.startswith("unmapped:"),
            }
        )
        for s in p.customers:
            signals.append(
                {
                    "run_id": run,
                    "attribute": p.attribute,
                    **s.model_dump(
                        include={"finding_id", "direction", "region", "share", "k", "n"}
                    ),
                    "ci_low": s.ci_low,
                    "ci_high": s.ci_high,
                    "thin": s.thin,
                    "differs_from": s.differs_from,
                    "p_value": s.p_value,
                }
            )
        for i, v in enumerate(p.competitor_values):
            values.append(
                {
                    "run_id": run,
                    "attribute": p.attribute,
                    "ordinal": i,
                    **v.model_dump(
                        include={
                            "unit",
                            "condition",
                            "region",
                            "n",
                            "minimum",
                            "median",
                            "maximum",
                            "lower_is_better",
                            "ours",
                            "ours_rank",
                            "field_size",
                            "ours_vs_median",
                            "finding_ids",
                        }
                    ),
                }
            )
        for i, q in enumerate(p.quotes):
            quotes.append(
                {
                    "run_id": run,
                    "attribute": p.attribute,
                    "ordinal": i,
                    "source_id": q.source_id,
                    "direction": q.direction,
                    "text": q.text,
                }
            )
        for i, t in enumerate(p.sub_themes):
            themes.append(
                {
                    "run_id": run,
                    "attribute": p.attribute,
                    "ordinal": i,
                    "direction": t.direction,
                    "name": t.name,
                    "k": t.k,
                    "of_total": t.of,
                    "method": t.method,
                    "source_ids": list(t.source_ids),
                }
            )
        for t in {t.finding_id: t for t in p.trends}.values():
            trends.append(
                {
                    "run_id": run,
                    "attribute": p.attribute,
                    "finding_id": t.finding_id,
                    "claim": t.claim,
                    "polarity": t.polarity,
                    "horizon": t.horizon,
                    "n_independent_sources": t.n_independent_sources,
                    "thin": t.thin,
                }
            )
    requirements = []
    for c in a.requirement_candidates:
        t = c.target
        requirements.append(
            {
                "run_id": run,
                "req_id": c.id,
                "attribute": c.attribute,
                "title": c.title,
                "statement": c.statement,
                "customer_value": c.customer_value,
                "sub_theme": c.sub_theme,
                "assessment": c.assessment,
                "change_intent": c.change_intent,
                "baseline_status": c.baseline_status,
                "baseline_rationale": c.baseline_rationale,
                "target_operator": t.operator if t else None,
                "target_value": t.value if t else None,
                "target_unit": t.unit if t else None,
                "target_condition": t.condition if t else None,
                "target_rule": t.rule if t else None,
                "lower_is_better": c.lower_is_better,
                "options": json.dumps([o.model_dump() for o in c.options]),
                "acceptance": c.criterion.model_dump_json(),
                "customer_facts": list(c.customer_facts),
                "open_points": list(c.open_points),
                "evidence_ids": list(c.evidence_ids),
                "regions": list(c.regions),
                "priority": c.priority,
                "status": c.status,
                "wording": c.wording,
            }
        )
    referenced = {
        *(i for x in a.feature_assessments for i in x.cited_ids),
        *(i for c in a.requirement_candidates for i in c.evidence_ids),
        # one example per sub-theme; quote texts are already in analysis_quotes
        *(t.source_ids[0] for p in a.evidence_packages for t in p.sub_themes if t.source_ids),
    }
    findings, sources, links = [], {}, []
    for report in a.reports.values():
        for s in report.sources:
            # Storage is shared: feedback items are copied only when a judgment or requirement
            # cites them, or as one example per sub-theme (so every cited id resolves); excerpts are capped.
            if s.kind == "feedback" and s.id not in referenced:
                continue
            ref = s.references[0] if s.references else None
            sources[s.id] = {
                "run_id": run,
                "source_id": s.id,
                "kind": s.kind,
                "source_type": _source_type(s),
                "title": s.title or None,
                "ref": s.ref,
                "url": s.ref if s.kind == "web" else None,
                "excerpt": s.excerpt[:EXCERPT_CHARS],
                "locator": ref.locator.model_dump_json() if ref and ref.locator else None,
                "retrieved_at": s.retrieved_at,
                "limitations": list(dict.fromkeys(s.limitations))[:2],
            }
        for f in report.findings:
            q, st = f.quantity, f.stats
            findings.append(
                {
                    "run_id": run,
                    "finding_id": f.id,
                    "agent": f.agent,
                    "attribute": f.attribute,
                    "subject": f.subject,
                    "claim": f.claim,
                    "polarity": f.polarity,
                    "direction": f.direction,
                    "region": f.region,
                    "confidence": f.confidence,
                    "value": q.value if q else None,
                    "unit": q.unit if q else None,
                    "qualifier": q.qualifier if q else None,
                    "value_origin": q.origin if q else None,
                    "k": st.k if st else None,
                    "n": st.n if st else None,
                    "ci_low": st.ci_low if st else None,
                    "ci_high": st.ci_high if st else None,
                    "thin": st.thin if st else None,
                    "denominator": st.denominator_label if st else None,
                    "horizon": f.horizon,
                }
            )
            links += [
                {"run_id": run, "finding_id": f.id, "source_id": sid}
                for sid in dict.fromkeys(f.source_ids)
            ]
    cited = {x["source_id"] for x in links}
    out |= {
        "analysis_features": features,
        "analysis_requirements": requirements,
        "analysis_findings": findings,
        # Sources a finding or a judgment cites; only links to stored sources.
        "analysis_sources": [v for k, v in sources.items() if k in cited or k in referenced],
        "analysis_finding_sources": [x for x in links if x["source_id"] in sources],
        "analysis_customer_signals": signals,
        "analysis_competitor_values": values,
        "analysis_quotes": quotes,
        "analysis_sub_themes": themes,
        "analysis_trends": trends,
    }
    return out


def write(rows: dict[str, list[Row]], database_url: str) -> None:
    import psycopg

    run_id = rows["analysis_runs"][0]["run_id"]
    with psycopg.connect(database_url, connect_timeout=20) as conn, conn.transaction():
        conn.execute(MIGRATION.read_text())  # type: ignore[arg-type]
        conn.execute("DELETE FROM analysis_runs WHERE run_id = %s", (run_id,))  # cascades
        for table, items in rows.items():  # analysis_runs first (dict order)
            if not items:
                continue
            cols = list(items[0])
            sql = (
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
            )
            with conn.cursor() as cur:
                cur.executemany(sql, [tuple(r[c] for c in cols) for r in items])  # type: ignore[arg-type]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--write", action="store_true", help="write to DATABASE_URL")
    args = parser.parse_args()
    analysis = SituationAnalysis.model_validate_json(args.analysis.read_text())
    rows = rows_of(analysis)
    for table, items in rows.items():
        print(f"{table:28} {len(items):6} rows")
    if not args.write:
        print("dry run: nothing written (use --write)")
        return
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    write(rows, url)
    print(f"written: run {analysis.run_id}")


if __name__ == "__main__":
    main()
