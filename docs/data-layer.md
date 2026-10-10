# Knowledge layer and orchestration v1 handoff

This is the first database-independent read integration. `bmwow.knowledge` projects
a validated ontology v0.2.0 snapshot into typed records that situation-analysis
agents can consume. The included demonstration uses only the existing invented
fixture. Neon provisioning, the SQL adapter, private ingestion, and ontology
writes are pending. The raw-data adapter and ontology contracts are unchanged.

## Run without Neon

From the repository root:

```sh
uv sync --locked
uv run python -m scripts.inspect_knowledge
uv run python -m scripts.inspect_knowledge --json
uv run pytest
```

No database, LLM credentials, web requests, or original BMW files are needed for
the inspection script. It exercises the same `ModuleBackend` used by orchestration
v1 and prints capabilities, feedback, study measurements, and combined future
sales with their original qualifications. Synthetic setup is explicit: the factory
rejects any snapshot containing a non-synthetic SourceDocument.

On this macOS checkout, a hidden editable-install `.pth` can prevent imports from
`.venv`. Use a temporary environment prefix in zsh when needed:

```sh
UV_PROJECT_ENVIRONMENT=venv uv sync --locked
UV_PROJECT_ENVIRONMENT=venv uv run python -m scripts.inspect_knowledge
```

Apply that prefix to each `uv` command using this environment. It changes no shell
configuration and requires no permanent export. See README troubleshooting for
the alternative of clearing the local hidden flag.

## Boundaries and ownership

- `backend/bmwow/ontology/` remains the source of truth for graph objects,
  relationships, validation, and generated JSON contracts. Its version stays 0.2.0.
- `backend/bmwow/knowledge/records.py` defines **read projections**, not additional
  graph node types. It reuses ontology Context, Locator, Measurement, and NumericRange.
- `repository.py` defines `SnapshotRepository.load_snapshot() -> GraphBundle`.
  `InMemoryRepository` validates a complete snapshot and returns isolated copies.
- `service.py` provides deterministic reads over one fixed, validated snapshot.
  Construct and inject a new service when the dataset version changes. Read results
  and configuration are copies; consumers cannot mutate the stored graph.
- `config.py` holds explicit application curation: segment profiles, sale regions,
  market search locales, feature keys, reviewed VFC mappings, and combined sales
  group labels. It does not guess missing product metadata.
- `synthetic.py` supplies invented configuration for the tracked fixture only.
- `src/models/knowledge.py` reexports the read models for existing imports.
  `src/knowledge/` is a thin temporary v1 compatibility boundary. New backend
  logic belongs in `backend/bmwow/`; the existing `src/agent/` layout is retained
  while the orchestration owner evolves v1. Run it from the checkout: `src` is
  not included in the installed `bmwow` wheel.

All Python dependencies, including the existing LangChain/LangGraph, OpenAI,
Firecrawl, SQLite checkpoint, and clustering integrations, are declared and locked
at the root. `pyproject.toml.bak` is historical and is not an installation input.
Tests use fake LLM/search providers; installing these integrations does not call them.

## Inject the service

The application startup code owns configuration, storage, and injection:

```python
from bmwow.knowledge import KnowledgeService
from src.knowledge import configure_service

# repository and config are supplied by the application, not created by the agents.
configure_service(KnowledgeService(repository, config))
```

With `KNOWLEDGE_BACKEND=real` (v1's default), `ModuleBackend` imports
`src.knowledge.ontology` and `src.knowledge.sql_client`; both delegate to that
service. Existing signatures and imports are preserved. The bridge accepts sync
or async functions, including iterable feedback results. An unconfigured real
backend raises an actionable error; it never silently substitutes synthetic data.
The existing `KNOWLEDGE_BACKEND=fake` remains the separate v1 agent-test backend.

Available reads: model registry, regions, model, portfolio, competitors, taxonomy,
capabilities, feedback, sales, study scores, lexical document search, and citation
resolution. `get_study_scores(models, regions)` is an optional additive bridge
method; older modules without it return an empty list. It does not mean v1 now
contains a complete deterministic study-analysis agent.

## Qualifications agents and frontend must retain

**Identity and citations.** Every projected observation carries EvidenceReference
objects with original Evidence ID, SourceDocument ID, record key, and exact locator.
Capabilities cite their existing Signal and retain its underlying evidence links.
Original record IDs, not repeated classification rows, identify feedback items.
The richer optional fields survive v1 coercion and `Source` JSON serialization.
Use those fields in source views; the bounded text excerpt is a preview.

Sales retrieval retains the legacy `sql:<query_hash>` summary source and adds one
`kg:<Evidence ID>` source per original row. The baseline agent cites row sources
when available. `resolve_citation()` accepts an original ID or `kg:` / `fb:` wrapper
and returns the graph object; a query hash is not an original graph node. Resolve
Source.references for the originals behind a query, and use existing ontology
trace helpers for a capability's chain.

**Model identity and geography.** Generation queries select the generation object,
not an arbitrary variant. Variant-only capabilities remain variant-scoped. Unknown
models return no match; ambiguous identities raise. A model needs an explicit segment
profile for v1 because that field is absent from the canonical VehicleModel.
Profiles include a curation note; the synthetic segment is invented.

`ModelNode.regions` and `data_coverage` describe evidence coverage, including zero
sales and combined rows. They do not prove the model is sold there. Portfolio reads
use separately curated `sold_regions`. Competitor reads also require an existing
COMPETES_WITH relationship. The resolver uses curated availability for these
qualified records, rather than treating empty coverage as worldwide availability.
Country-to-region mapping uses explicit Market.country_codes; it does not assume
DE means EU. A sales row retains its original regional grain. Do not add a regional
total to its constituent country totals.

**Capabilities and ranges.** Availability, conditions, epistemic status, scope,
measurement, limitations, and locators are retained. Standard and optional claims
are separate records. A range remains structured `value_range`; the legacy value
field renders its endpoints as text. No midpoint is invented. A month-only catalog
date does not become a day or establish fresh capability evidence. The competitor
agent treats a traced claim with unknown `as_of` as needing freshness research.
Catalog availability does not prove equipment fitted to a feedback author's car.

**Feedback.** One item represents one original Evidence record and retains all
classification locators, original VFC labels, nulls, `no_class_found`, engine type,
and country/model scope. Proposed mappings remain visible with `attribute=None`;
only reviewed mappings populate the feature key. The ontology does not currently
carry a distinct feedback event date, so a `since` filter excludes undated records
instead of borrowing observation or publication dates. `limit=0` returns none.

For traced records, v1 deduplicates by original evidence identity. Independent
comments with identical or similar wording remain in the denominator and may
cluster together. Legacy untraced test records retain v1's text/similarity dedupe.
Item shares describe the retrieved corpus; they are not customer-population shares.
Cross-source reposts require explicit source-independence handling at ingestion,
not an assumption that all similar text represents one person.

**Study results and documents.** Means, proportions, response categories, question
labels, units, unknown scales, sample sizes, denominators, and population notes
remain distinct. A share is not converted into a respondent count. Study cells
can also appear as document chunks with the original measurement rendered in text.
Publication precision is retained in `publication_label`; unknown day stays null.
The initial search is deterministic token overlap with optional kind/region filters,
not embeddings, semantic search, or a complete PDF retrieval implementation. No
matching evidence returns none; unknown scope is not assumed global.

**Sales.** Sales must be nonnegative scalar counts in vehicles. Explicit zeroes
are retained. Combined groups require an exact source label configured by original
Evidence ID and remain one unsplit observation even when both models are requested.
Historical becomes `actual`; `source_reported_future`, `forecast`, and `unknown`
retain their original meaning. Future/group rows are shown as qualified source
observations. The baseline excludes them from model-specific historical volume,
growth, and portfolio-share calculations and reports missing historical data as
partial coverage. A reported future value is not relabeled as a verified forecast.

## SQL/Neon adapter handoff

The SQL owner can retain raw spreadsheet-shaped tables. Before selecting queries,
agree the actual tables, immutable record keys, source/dataset versions, supported
models/markets, and ownership of imports. No schema or Neon resources are prescribed
or created by this slice.

Implement `SnapshotRepository` around that schema. Hydrate a closed graph with the
original SourceDocument/Evidence records and any already reviewed interpretation
nodes. Preserve original text and structured values; a locator alone cannot load
a workbook cell or PDF passage. Preserve classification grouping, scope, dates,
group identities, zeroes, range endpoints, unit/statistic distinctions, conditions,
and provenance. Use idempotent stable IDs tied to source versions and original
record identity. Unknown mappings remain unknown and should be reported.

Run `validate_bundle` on the **complete** hydrated snapshot before injection.
The service revalidates it and checks configuration references. This repository
interface is intentionally small for the first integration; if dataset size later
requires query-based reads, evolve the storage boundary with equivalent contract
tests. It currently provides no cache, auth, transaction, or concurrent-write API.
Use one agreed team dataset and expose approved backend reads; browser consumers
must not receive database credentials. Original files and database contents stay
in BMW-permitted storage outside GitHub, including private repositories and CI.

The synthetic registry includes only G60/G68; it is not the team's real-model
inventory. Real G70/F70/G60/G68 support requires SQL ingestion and reviewed
configuration. Adding a code to the YAML fallback does not establish data coverage.

## Write path and next milestone

`store_findings` is intentionally absent from the read service. The v1 optional
bridge returns `False`: an analysis may be saved to v1's ignored/local analysis
directory, but it is not stored in Neon or accepted into the ontology.

The next write integration must explicitly translate validated agent outputs into
candidate Signals/Needs/Trends/Assumptions with provenance and epistemic status,
validate the merged graph, and commit atomically against the expected snapshot.
SituationAnalysis and its Source records are read/analysis DTOs, not persisted
ontology objects. Requirement proposal validation and revision-specific human
Decision events remain separate. No source read or LLM finding grants approval.

Once SQL is ready, substitute the repository and curate configuration, then run
one real model/market/theme through retrieval and inspect its citations locally.
Next wire candidate ingestion, requirement synthesis, and the frontend dossier.
Coordinate boundary changes with both teammates rather than duplicating the
ontology models inside the agent or frontend layer.

## Verification

`tests/knowledge/` checks complete graph validation, copy isolation, metadata
preservation, conditional/ranged capabilities, classification grouping, explicit
country membership, zero and future/group sales, unknown study metadata, partial
dates, citation resolution, async bridge support, identity-based feedback dedupe,
and a real LangGraph run with the new backend and controlled reader nodes.
The graph test uses the real baseline node; its positioning LLM step and the other
three interpretation agents are replaced with controlled readers. Existing v1
tests separately exercise all four agents with fake LLM/search providers.

Run the root checks from AGENTS.md: pytest, Ruff lint/format, schema freshness, and
synthetic graph validation. This validates the integration behavior, not the merit
of real BMW proposals, actual SQL ingestion, or live provider calls.

Validation on 2026-10-10: **249 tests passed**, including 29 knowledge integration
tests. All 24 new/modified Python files pass Ruff lint and format checks; generated
contracts are current and the synthetic graph validates (57 nodes, 74 edges).
The inspection script works in both text and JSON modes. Root-wide Ruff checks
still fail on 22 pre-existing lint issues and 27 unformatted files outside this
change. The lint codes were compared with HEAD and the format failures checked
against the changed-file list. Those unrelated v1 cleanup items remain for a
separate change; no checks were disabled or relaxed.
