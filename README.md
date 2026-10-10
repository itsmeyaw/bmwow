# BMWow — BMW product decision assistant

EHL Munich hackathon project for the BMW challenge: turn customer feedback, studies,
sales data, public sentiment, competitor information, and trends into traceable
requirements for successor vehicles. Human review remains separate from agent proposals.

The repository has one **Python project managed by uv** and one **Next.js frontend
managed by pnpm**. All Python work, including ontology, orchestration, and
data adapters, shares the root `pyproject.toml`, `uv.lock`, and environment.

## Setup

Use Python 3.12 (selected by `.python-version`), [uv](https://docs.astral.sh/uv/),
and the pnpm version declared in `package.json`. Run commands from the repository root.

```sh
# Shared Python package and development tools
uv sync --locked
uv run bmwow-validate contracts/ontology/examples/synthetic.json

# Frontend
pnpm install
pnpm dev
```

Open http://localhost:3000 for the frontend. Python setup does not start an API or
agents. Orchestration v1 and a synthetic knowledge bridge are available; the Neon
adapter and the complete product-decision workflow remain to be integrated.
Run `uv run python -m scripts.inspect_knowledge` to exercise the bridge without
a database, API keys, or BMW input. See [the data-layer handoff](docs/data-layer.md).

Add Python dependencies with `uv add <package>` or `uv add --dev <package>` at the
root. Include both `pyproject.toml` and `uv.lock` in the change. Do not create separate
ontology or agent projects. Frontend dependencies stay in `package.json` and
`pnpm-lock.yaml`.

## Repository layout

```text
pyproject.toml / uv.lock       Shared Python dependencies and locked versions
backend/bmwow/                Importable Python package; future backend modules go here
  ontology/models.py          Canonical Pydantic models and field constraints
  ontology/relationships.py   Canonical relationship endpoints and descriptions
  ontology/validation.py      Structure and graph-wide rules; validation CLI
  ontology/tools.py           Typed queries, tracing, comparison checks and proposals
  ontology/schema.py          Generates and checks portable JSON contracts
  knowledge/                  Typed read records, snapshot interface, and projections
contracts/ontology/           Shared JSON artifacts for frontend, agents, and data adapters
  schema.json                 Generated JSON Schema; do not edit manually
  vocabulary.json             Generated vocabulary; do not edit manually
  agent-contracts.json         Generated agent-tool input/output schemas
  source-mappings.json         Curated mappings from supplied raw columns
  examples/synthetic.json     Shareable integration fixture, with invented evidence
docs/ontology.md              Ontology meaning, design factors, and integration guidance
docs/ontology-consumers.md    Worked dossier and frontend/orchestration handoff
docs/project-plan.md          Next milestones, team boundaries, and BMW data restrictions
docs/data-layer.md            Synthetic knowledge integration and SQL/orchestration handoff
docs/web-research.md          Proposed web evidence collection contract
scripts/inspect_parking_dossier.py  Runnable synthetic four-question example
scripts/inspect_knowledge.py   Synthetic read projections through orchestration v1
tests/ontology/               Contract, graph, interoperability, and CLI tests
tests/knowledge/              Synthetic read and v1 bridge integration tests
raw_data/                     Local BMW data and sample; ignored by Git
src/app/                      Next.js frontend
src/agent/                    Existing situation-analysis orchestration v1
src/knowledge/                Thin compatibility boundary to bmwow.knowledge
src/models/                   V1 analysis DTOs; knowledge records are reexports
package.json / pnpm-lock.yaml Frontend dependencies and scripts
AGENTS.md                     Guidance for coding agents
```

Python source belongs in `backend/bmwow/`, shared JSON artifacts in `contracts/`,
guides in `docs/`, and tests in `tests/`. The source package sits outside the repository
root, following the import isolation described by the
[Python Packaging Guide](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).

`backend/` is the Python source directory; `bmwow/` is the installed package
namespace. Keep both so imports such as `from bmwow.ontology import GraphBundle`
work consistently in tests, scripts, and future services. The wheel configuration
in `pyproject.toml` installs `backend/bmwow/`. Future LangChain agents and workflows
belong in `backend/bmwow/agents/`; `ontology/tools.py` contains deterministic domain
operations that those agents can call. Existing orchestration v1 is currently in
`src/agent/`; this slice retains its imports while new knowledge logic follows the
installed package layout. A later agent migration should be coordinated with its
owner. The v1 `src` modules currently require running from the checkout.

There is one ontology definition. Pydantic models and Python relationship rules
generate `contracts/ontology/schema.json`, `contracts/ontology/vocabulary.json`,
and `contracts/ontology/agent-contracts.json`.
`source-mappings.json` is a hand-maintained input mapping contract, and the synthetic
example is a hand-maintained integration fixture. The generator updates only the
three generated files. Guides explain the contract without defining another schema.

## Using the Python ontology

Pydantic is the schema authoring source of truth. JSON stays the interchange format
for the frontend, SQL adapters, and agent tools. **Version 0.2.0 is a breaking wire
extension**: catalog item identities, scoped capability claims, ranges and test
conditions, study/sales signal kinds, requirement change intent and baselines, and
criterion verification fields. Python import paths and existing fixture IDs remain
stable. Coordinate adapters and consumers using the
[migration guide](docs/ontology.md#migrating-v010-consumers-and-local-samples).

```python
from pathlib import Path

from bmwow.ontology import GraphBundle, validate_bundle

# Strict JSON parsing produces typed nodes, properties, dates, and timestamps.
bundle = GraphBundle.model_validate_json(
    Path("contracts/ontology/examples/synthetic.json").read_text(encoding="utf-8")
)
errors = validate_bundle(bundle)
if errors:
    raise ValueError("\n".join(errors))

payload = bundle.model_dump(mode="json")  # for API, frontend, or storage adapters
```

`GraphBundle` checks structure. **Also call `validate_bundle` before accepting a
bundle**: it checks references, endpoint types, deduplication, evidence chains,
scope transfers, measurements, and revision-specific human decisions. It accepts
a Python model or decoded JSON dictionary and returns errors (an empty list means
valid). A bundle is a closed snapshot. Validate an agent patch against the merged
snapshot so all referenced nodes are present.

Models reject unknown fields and type coercion. Nullable fields remain required:
use explicit `null` for unknown information. JSON dates use ISO dates and timestamps
include a timezone. For decoded tool payloads, call `validate_bundle(payload)` or
`GraphBundle.model_validate_json(json.dumps(payload))`. To construct models directly
in Python, supply native `date` and timezone-aware `datetime` values.

JSON Schema describes structure. Graph-wide rules live in Python and do not
automatically become JSON Schema rules. Frontend validation alone does not verify
evidence chains or human approval.

## Changing and checking the contract

1. Edit Python models in `backend/bmwow/ontology/models.py`; update
   `relationships.py` and `validation.py` when changing relationship or graph rules.
2. Update fixtures and tests. Coordinate and version breaking wire changes with
   the frontend and orchestration teammates.
3. Regenerate contracts and run the checks below. Include source, generated files,
   tests, and relevant documentation in the same change.

```sh
uv run bmwow-schema
uv run bmwow-schema --check
uv run bmwow-validate contracts/ontology/examples/synthetic.json
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`bmwow-schema --check` fails on missing or stale generated files.
The default output directory is `contracts/ontology`, relative to the current directory.
`bmwow-validate` accepts multiple files and exits with status 1 on invalid input.
These commands can be used in CI. Export elsewhere with
`uv run bmwow-schema --output-dir <directory>`.

The ignored `raw_data/ontology_examples/feedback-and-sales.json` is a legacy v0.1.0
BMW sample. It has not been silently rewritten or deleted. Follow the migration
guide before validating it with the v0.2.0 CLI; changing the version alone is insufficient.

Keep original BMW data and derived samples in ignored `raw_data/`. Tracked fixtures
use synthetic content and serve integration, not research evidence.

Frontend checks remain `pnpm lint`, `pnpm fmt:check`, and `pnpm build`. Read the
applicable installed Next.js guide as directed by `AGENTS.md` before frontend changes.

## Team handoff

See the [project plan](docs/project-plan.md) for the complete evidence-to-review
workflow and the next milestone. Ontology v0.2.0 is the shared contract. Orchestration
v1 now has a [synthetic read bridge](docs/data-layer.md); private ingestion, the Neon
adapter, candidate ingestion, synthesis, and the review API/UI remain next.

Start with the [consumer guide](docs/ontology-consumers.md) and run
`uv run python scripts/inspect_parking_dossier.py`. It answers the four product
questions from the existing dossier while retaining each edge's target and
rationale. Add `--json` for the existing generated RequirementDossier payload.

- **Ontology/backend:** import `bmwow.ontology` and extend the shared Python package.
  See [ontology guide](docs/ontology.md) for entity meaning, limits, IDs, and revisions.
- **Agent orchestration:** use typed models for tool payloads and proposals; run
  graph validation before accepting results. Preserve original Evidence and
  source locators. Deterministic helpers in `backend/bmwow/ontology/tools.py` support
  scoped query, incoming/outgoing traversal, evidence trace, requirement context,
  comparison readiness, and non-mutating proposal validation. Their schemas are in
  `agent-contracts.json`; see the ontology guide for signatures and limits. Wrap
  these in LangChain tools using injected runtime graph access. Orchestration,
  persistence, authentication, and concurrent-write control remain service work.
- **Frontend:** use generated JSON contracts and the synthetic fixture for requirement
  and evidence views, including change intent, baseline claims, package conditions,
  test conditions, opposing evidence, and revision-specific decisions. No TypeScript
  generator or API endpoint has been selected yet.
- **SQL/data:** raw tables can retain the supplied column layout. Map them through
  adapters into Evidence and related nodes; the ontology is not the required raw
  SQL table design. Neon is the selected shared PostgreSQL provider; agree one
  canonical dataset and coordinated imports/migrations. Its setup and adapter are
  still pending. See [shared database plan](docs/project-plan.md#shared-database-neon)
  and [source mappings](contracts/ontology/source-mappings.json).
- **Web research:** public sentiment, competitor claims, and trends use the same
  evidence contract. See [collection guidance](docs/web-research.md).
  No scraper has been implemented yet.

The [implementation plan](docs/ontology-plan.md) records the design decisions and
acceptance questions. The ontology follows business-object and validated-change
principles from Palantir while retaining source evidence and uncertainty explicitly.
The tracked fixture exercises feedback, public opinions, competitor/trend claims,
BMW baseline and package identities, conditional charging, an interval, study
statistics, combined-model future sales, and opposing evidence. Every claim and
number in that fixture is invented; it does not establish a BMW product fact.

## Layout migration

The former top-level `ontology/` directory has been removed. Its JSON artifacts and
examples now live in `contracts/ontology/`. Its README is now `docs/ontology.md`,
and its web research guide is now `docs/web-research.md`. Update file imports or
scripts that use the old artifact paths. Python imports (`bmwow.ontology`), CLI
names, dependency files, and the ontology version remain the same.

## Sharing with teammates

**BMW prohibits uploading its data to GitHub, including private repositories.**
Share code, schemas, migrations, and synthetic fixtures through GitHub. Keep
originals and data-bearing derivatives, exports, embeddings, generated proposals,
screenshots, and logs/transcripts local or in BMW-permitted storage. The team's
current understanding permits an access-controlled server database outside
GitHub; Neon is the selected provider. Commit its migrations and import scripts,
but not its contents or credentials. GitHub CI and build artifacts must use
synthetic content. See the
[data boundary](docs/project-plan.md#bmw-data-boundary).

Use [issue #3](https://github.com/itsmeyaw/bmwow/issues/3) for sanitized agent
discussion and proposals. Agents must receive explicit human confirmation in
their own chat before making real changes; issue comments never constitute that
confirmation. See [the coordination guide](docs/agent-coordination.md) for privacy,
proposal handling, and rule loading. `AGENTS.md` holds the shared policy, and
`CLAUDE.md` imports it for Claude Code.

Commit Python source, frontend source, tests, docs, `AGENTS.md`, shared tool
configuration, `.python-version`, both dependency lockfiles, and the generated
JSON contracts. Generated contracts belong in Git so frontend and orchestration
teammates can use the same payloads without running Python generation themselves.

Keep `raw_data/`, real BMW excerpts and exports, `.env` files, local databases,
virtual environments, caches, coverage output, logs, and local agent transcripts
out of Git. The ignore rules cover these paths. A sanitized `.env.example` may be
committed when the application has actual environment variables to document.
SQL migrations and seed scripts belong in Git; local SQLite/libSQL database files do not.

`AGENTS.md` gives coding agents the shared project conventions. The short Cursor
rule in `.cursor/rules/project.mdc` points to that file, keeping the guidance in
one place. Existing shared skills and tool configuration may stay tracked;
personal overrides and generated session state should remain local.

Use a separate feature branch for each person's work and merge through a small PR.
Coordinate changes to wire fields, IDs, API boundaries, and lockfiles with the
other two teammates. Include generated contracts and updated integration docs
with any schema change. Inspect the staged diff before committing; `.gitignore`
does not remove files that were already tracked.

### Entire checkpoint sharing

This repository has Entire hooks enabled. The pre-push hook can upload captured
prompts, transcripts, and tool results in separate Git checkpoint refs even though
`.entire/metadata/` is ignored in the working tree. This is separate from source-file
tracking; see [Entire session storage](https://docs.entire.io/guides/checkpoints/checkpoint-storage).

For a code-only push, keep checkpoints local in your clone:

```sh
entire configure --local --skip-push-sessions
```

This writes `strategy_options.push_sessions: false` to ignored
`.entire/settings.local.json`. Capture continues locally; each teammate must apply
this setting in their clone for this project. Do not push checkpoint refs or
`entire/*` branches with `--all` or `--mirror` when you intend to share only source
code. This option does
not remove checkpoint history that was already pushed. Checkpoints containing
BMW data must stay out of GitHub too. See
[keeping checkpoints local](https://docs.entire.io/guides/checkpoints/keep-checkpoints-local).

## macOS environment troubleshooting

If installation succeeds but importing `bmwow` fails, run
`uv run python -v -c 'import bmwow'` and look for a skipped hidden `.pth` file.
Python ignores files with the macOS hidden flag. For this local environment,
clearing that flag with `chflags -R nohidden .venv` repairs the editable install.
If another process keeps restoring hidden flags, use a nonhidden environment
directory and set `UV_PROJECT_ENVIRONMENT=venv` for both sync and run commands.
See [the CPython issue](https://github.com/python/cpython/issues/148121).
