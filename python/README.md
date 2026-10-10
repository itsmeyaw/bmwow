# BMWow Python reference implementation

This is where teammates who work in Python write the backend logic. The product
runs in TypeScript (`../src/server/`), and each module here gets ported there.
Until a module is ported, the Python code and its tests count as its spec. After
that, the TypeScript version does (see `../AGENTS.md`).

Run everything below from this directory. The project uses Python 3.12 (pinned
in `.python-version`) and [uv](https://docs.astral.sh/uv/). The `.env` file,
`data/`, and `contracts/` stay at the repository root.

```sh
uv sync --locked
uv run pytest
uv run python -m scripts.inspect_knowledge      # synthetic knowledge bridge, no keys or DB
uv run python scripts/inspect_parking_dossier.py  # the four product questions; add --json
uv run python -m scripts.inspect_neon_feedback --env-file ../.env  # private Neon feedback; aggregates only
```

The Neon check needs `DATABASE_URL` and makes no LLM, embedding, or web calls; see
[the knowledge layer guide](../docs/data-layer.md#run-the-feedback-slice).

For private sales/study imports and the combined snapshot/Neon service, follow
[the ingestion plan](../docs/knowledge-ingestion.md). The analysis CLI accepts
`--snapshot`, `--knowledge-config`, and `--env-file`; `--resolve-only` checks the
brief without provider calls. Run its aggregate inspection command before analysis.

Add dependencies with `uv add <pkg>` or `uv add --dev <pkg>`, and commit
`pyproject.toml` and `uv.lock` together.

## Layout

```text
bmwow/ontology/   Canonical Pydantic models, relationship rules, graph validation,
                  deterministic tools, contract generator (bmwow-schema, bmwow-validate)
bmwow/knowledge/  Snapshot/Neon/combined reads, curation manifests, workbook import,
                  validated local candidate acceptance
bmwow/agent/      Situation-analysis orchestration v1 (LangGraph); see bmwow/agent/README.md
  models/         v1 evidence DTOs (knowledge records are reexports)
  knowledge_bridge/  v1 module paths that delegate to bmwow.knowledge
tests/            ontology/, knowledge/, and agent tests; tests/fakes/ hold in-memory backends
scripts/          Synthetic examples, private import/inspection, and the v1 analysis CLI
```

## Ontology contract

Pydantic models in `bmwow/ontology/models.py` and the rules in
`relationships.py` are the single ontology definition. From them, `bmwow-schema`
generates `../contracts/ontology/{schema,vocabulary,agent-contracts}.json`. The
frontend and the TypeScript port read those files, so never edit them by hand.
`source-mappings.json` and `examples/synthetic.json` are maintained by hand.

```python
from pathlib import Path
from bmwow.ontology import GraphBundle, validate_bundle

bundle = GraphBundle.model_validate_json(
    Path("../contracts/ontology/examples/synthetic.json").read_text(encoding="utf-8")
)
errors = validate_bundle(bundle)  # [] means valid
```

`GraphBundle` only checks structure. Before you accept a bundle, also run
`validate_bundle` on the complete merged snapshot. It checks references, endpoint
types, deduplication, evidence chains, scope transfers, measurements, and
revision-specific human decisions. Models reject unknown fields and type
coercion. Nullable fields are still required, so pass `null` explicitly. Dates
are ISO dates, and timestamps must include a timezone.

Version 0.2.0 is a breaking wire extension of v0.1.0. See the
[migration guide](../docs/ontology.md#migrating-v010-consumers-and-local-samples).
The combined knowledge milestone does not change that ontology version or the
existing v1 read records. SQL feedback/aspects remain read projections until an
explicit graph ingestion creates their SourceDocument/Evidence/Signal chains.
`FileCandidateStore` validates and atomically accepts non-Requirement candidates
against an expected snapshot fingerprint. Requirement proposals and authenticated
human Decisions require their own service write paths; the analysis write hook
is still unconnected. See [the write boundary](../docs/data-layer.md#candidate-acceptance-and-orchestration-handoff).

To change the contract:

1. Edit `models.py`, plus `relationships.py` and `validation.py` for relationship
   or graph rules.
2. Update the fixtures and tests. Coordinate breaking wire changes with the
   frontend and TypeScript owners.
3. Regenerate and check:

```sh
uv run bmwow-schema            # writes ../contracts/ontology by default
uv run bmwow-schema --check
uv run bmwow-validate ../contracts/ontology/examples/synthetic.json
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## macOS: `import bmwow` fails after a successful sync

Python skips `.pth` files that carry the macOS hidden flag. To confirm, run
`uv run python -v -c 'import bmwow'` and look for a skipped hidden `.pth`. Fix
it with `chflags -R nohidden .venv`, or use `UV_PROJECT_ENVIRONMENT=venv`. See
[the CPython issue](https://github.com/python/cpython/issues/148121).
