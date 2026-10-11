# Knowledge layer and orchestration v1 handoff

`bmwow.knowledge` supplies typed reads from a validated ontology v0.2.0 snapshot,
the existing private Neon feedback tables, or both through `CombinedKnowledgeService`.
The synthetic demonstration uses only the invented fixture. The feedback-only
service reads SQL feedback/aspects; the combined service adds snapshot-backed
sales, studies, documents, and curated capabilities through the same v1 interface.
Workbook ingestion and local candidate acceptance are implemented. Requirement
persistence, human review services, and the analysis write hook remain pending.
The raw SQL schema, generated ontology contracts, and v1 wire field names are unchanged.

## Run without Neon

From `python/`:

```sh
uv sync --locked
uv run python -m scripts.inspect_knowledge
uv run python -m scripts.inspect_knowledge --json
uv run pytest
```

No database, LLM credentials, web requests, or original BMW files are needed for
the inspection script. It exercises the same `ModuleBackend` used by orchestration
v1 and prints capabilities, feedback, study measurements, and combined future
sales with their original qualifications. Synthetic setup is explicit: `create_synthetic_service`
rejects any snapshot containing a non-synthetic SourceDocument.

If `import bmwow` fails on macOS, see the troubleshooting note in
[`python/README.md`](../python/README.md).

## Boundaries and ownership

See [definition boundaries](definitions.md) for canonical type ownership and the
differences between graph objects, read projections, and analysis DTOs.

- `python/bmwow/ontology/` remains the source of truth for graph objects,
  relationships, validation, and generated JSON contracts. Its version stays 0.2.0.
- `python/bmwow/knowledge/records.py` defines **read projections**, not additional
  graph node types. It reuses ontology Context, Locator, Measurement, and NumericRange.
- `repository.py` defines `SnapshotRepository.load_snapshot() -> GraphBundle`.
  `InMemoryRepository` validates a complete snapshot and returns isolated copies;
  `FileSnapshotRepository` reads and validates a private JSON snapshot.
- `feedback.py` defines the query-based `FeedbackRepository` port and the partial
  `FeedbackKnowledgeService`. It does not wrap SQL feedback in an invented graph.
- `neon.py` implements that port with Psycopg 3 against `public.feedback_entries`
  and `public.feedback_aspects`. Each operation owns a short read-only transaction.
- `service.py` provides deterministic reads over one fixed, validated snapshot.
  Construct and inject a new service when the dataset version changes. Read results
  and configuration are copies; consumers cannot mutate the stored graph.
- `combined.py` reconciles SQL Derivates with canonical graph model IDs, combines
  dataset coverage, and routes citations while preserving original feedback fields.
  SQL registry coverage is captured at construction; construct a new service to
  refresh it. Feedback record reads and SQL citations still query the current import.
- `config.py` holds explicit application curation: segment profiles, sale regions,
  market search locales, feature keys, proposed/reviewed VFC/study/aspect mappings, and combined sales
  group labels. It does not guess missing product metadata.
- `manifest.py` defines the private `CurationManifest`: context nodes, knowledge
  configuration, feedback identities, source-specific markets, and pending decisions.
- `workbooks.py` imports original sales/study measurements with source-version
  identity and cell locators. `ingestion.py` validates merges and implements a
  separate atomic local candidate store. See [the ingestion guide](knowledge-ingestion.md).
- `factory.py` exposes `create_knowledge_service`: it requires an explicit feedback
  repository or `DATABASE_URL`, with no synthetic or feedback-only fallback.
- `synthetic.py` supplies invented configuration for the tracked fixture only.
- `bmwow.agent.models.knowledge` reexports the read models for v1 imports.
  `bmwow.agent.knowledge_bridge` is a thin temporary v1 compatibility boundary.

All Python dependencies, including openpyxl, Psycopg, LangChain/LangGraph, OpenAI, Firecrawl,
and SQLite checkpoint integrations, are declared and locked in
`python/pyproject.toml`. Tests use fake LLM/search providers; installing these
integrations does not call them.

## Inject the service

The application startup code owns configuration, storage, and injection:

```python
import os
from pathlib import Path

from bmwow.knowledge import create_knowledge_service
from bmwow.agent.knowledge_bridge import configure_service

# Run from python/. Load the private environment in application startup first.
service = create_knowledge_service(
    Path("../data/knowledge/snapshot.json"),
    Path("../data/knowledge/snapshot.config.json"),
    database_url=os.environ["DATABASE_URL"],
)
configure_service(service)
```

For snapshot-only reads, inject `KnowledgeService(repository, config)` instead;
the feedback-only setup is below. The combined factory validates the snapshot
and queries SQL coverage at construction, so it needs a live feedback connection.
The [private inspection command](knowledge-ingestion.md#inspect-and-connect) resolves
a brief and checks bounded feedback, sales/studies, and citations without providers.

With `KNOWLEDGE_BACKEND=real` (v1's default), `ModuleBackend` imports
`bmwow.agent.knowledge_bridge.ontology` and `.sql_client`; both delegate to that
service. Existing signatures and imports are preserved. The bridge accepts sync
or async functions, including iterable feedback results. An unconfigured real
backend raises an actionable error; it never silently substitutes synthetic data.
The existing `KNOWLEDGE_BACKEND=fake` remains the separate v1 agent-test backend.

Registry and taxonomy YAML fallbacks apply only to the bridge's `None` signal for
an unavailable optional contract. Empty responses are authoritative. Implemented
function errors propagate instead of substituting placeholder model/region or
taxonomy data: request resolution reports registry failures, and agent failure
isolation records taxonomy failures in the affected report.

Snapshot reads: model registry, regions, model, portfolio, competitors, taxonomy,
capabilities, feedback, sales, study scores, lexical document search, and citation
resolution. `get_study_scores(models, regions)` is an optional additive bridge
method; older modules without it return an empty list. It does not mean v1 now
contains a complete deterministic study-analysis agent.

The feedback-only Neon backend supplies registry, model metadata from feedback coverage,
feedback/aspects, retrieval metadata, and SQL citation resolution. Optional bridge
methods `get_feedback_page()` and `get_data_availability()` expose the bounded
selection and connected dataset kinds. Snapshot backends return `None` for these
optional additions; existing `get_feedback_items() -> list[FeedbackItem]` stays intact.
The combined service supplies both additions and the graph read methods. Its
availability flags describe connected source kinds, not completeness for every
model, region, Feature, or catalog claim.

## Qualifications agents and frontend must retain

**Identity and citations.** Every graph-projected observation carries EvidenceReference
objects with original Evidence ID, SourceDocument ID, record key, and exact locator.
Capabilities cite their existing Signal and retain its underlying evidence links.
Original record IDs, not repeated classification rows, identify feedback items.
The richer optional fields survive v1 coercion and `Source` JSON serialization.
Use those fields in source views; the bounded text excerpt is a preview.

Sales retrieval retains the legacy `sql:<query_hash>` summary source and adds one
`kg:<Evidence ID>` source per original row. The baseline agent cites row sources
when available. `resolve_citation()` accepts an original ID or `kg:` / `fb:` wrapper
and returns the graph object on a snapshot backend; a query hash is not an original graph node. Resolve
Source.references for the originals behind a query, and use existing ontology
trace helpers for a capability's chain.
On the combined service, graph IDs resolve to graph objects and SQL IDs resolve
to feedback read projections. Feedback contexts use canonical VehicleModel IDs
when configured; original countries, record IDs, aspect IDs, and locators remain
intact. Graph and SQL citation namespaces must not overlap.

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
Snapshot country-to-region mapping uses explicit Market.country_codes. The SQL
feedback backend uses the explicit EU membership policy described below. A sales
row retains its original regional grain. Do not add a regional
total to its constituent country totals. The combined service unions coverage
without adding sales/study market IDs to SQL feedback contexts. In the curation
template, `market:sales:EU` and `market:studies:EU` have separate IDs and unknown
country populations. They are selected by their source code for sales/study reads;
feedback `EU` remains the EU member-country query policy.

The v1 baseline still asks for sales using `brief.markets`. When these are feedback
country selectors, they do not select source Europe totals when the source's
country population is unknown. For grouped source context, call
`sales_volume(["G60"], ["EU"])` explicitly and retain its original scope. The
orchestration owner still needs to connect that source-region context to analysis;
assigning countries to a source group solely to make a query match is not valid.

**Capabilities and ranges.** Availability, conditions, epistemic status, scope,
measurement, limitations, and locators are retained. Standard and optional claims
are separate records. A range remains structured `value_range`; the legacy value
field renders its endpoints as text. No midpoint is invented. A month-only catalog
date does not become a day or establish fresh capability evidence. The competitor
agent treats a traced claim with unknown `as_of` as needing freshness research.
Catalog availability does not prove equipment fitted to a feedback author's car.
`get_attribute_values()` excludes Signals targeted by `SUPERSEDES`. Full snapshots
and citation resolution retain the earlier revisions for history and exact-revision
dossiers. A single reported maximum range uses a scalar; a structured interval
preserves the source's actual lower and upper bounds.

**Feedback.** One item represents one original Evidence record and retains all
classification locators, original VFC labels, nulls, `no_class_found`, engine type,
and country/model scope. Proposed mappings remain visible with `attribute=None`;
only reviewed mappings populate the feature key. The ontology does not currently
carry a distinct feedback event date, so a `since` filter excludes undated records
instead of borrowing observation or publication dates. `limit=0` returns none.
For SQL records, exact reviewed VFC mappings are applied by the combined service.
`get_aspect_mapping(citation_id)` exposes proposed/reviewed mapping metadata
separately for original or inferred Aspect Terms; it does not rewrite stored labels
or accept an aspect as a graph Signal. The initial manifest supplies no Feature
matches. That helper is a combined-service method, not a new v1 bridge tool.

For traced records, v1 deduplicates by original evidence identity. Independent
comments with identical or similar wording remain in the denominator. Legacy
untraced test records retain v1's normalized-text dedupe.
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

### Run the feedback slice

Put `DATABASE_URL` in an ignored local environment file. Keep it server-side.
From `python/`:

```sh
uv sync --locked
uv run python -m scripts.inspect_neon_feedback \
  --env-file ../.env --derivate G70 --country US --limit 50
```

The command temporarily injects the SQL read service, uses the real v1
`ModuleBackend`, round-trips Source metadata, and resolves sampled feedback and
aspect citations. It prints aggregate validation results and dataset availability,
not Verbatim, Quotes, IDs, embeddings, or credentials. It makes no model/provider
calls or database writes. Live checks are opt-in; ordinary pytest uses synthetic
data. A zero-result selection is valid and performs no citation checks.

Application startup, after loading its private environment, uses:

```python
from bmwow.knowledge.neon import create_neon_feedback_service
from bmwow.agent.knowledge_bridge import configure_service

configure_service(create_neon_feedback_service())  # reads DATABASE_URL; lazy connection
```

`NeonFeedbackConfig` controls dataset namespace, default/hard limits, timeouts,
and connection establishment retries. It defaults to two attempts for transient
connection failures; authentication errors and queries are not replayed.
The default selection is at most 200 feedbacks; the hard cap is 5,000. `None` is a
bounded default, not an unbounded export. `FeedbackServiceConfig.model_profiles`
accepts explicit `ModelProfile` objects keyed by Derivate. A missing profile leaves
the segment `unknown`; it does not derive segment or sale availability from feedback.
Curate that metadata before launching competitor research or the full analysis.

### Query and aspect contract

Filters preserve the existing `models`/`markets` wire names (Derivate/ISO country),
with additive `engine_types` and `sources`. Source A–D meanings remain unknown.
For SQL feedback, `markets=["EU"]` expands to the 27 EU member country codes before
the count and parent-selection queries. Mixed selections such as `["EU", "DE", "US"]`
are deduplicated. Direct country filters such as `["DE"]` still select that country.
The parent selection is ordered by Feedback Explorer ID using C collation and
limited **before** fetching its aspects. The count query counts feedback, never
joined aspects. All queries in one retrieval share a repeatable-read snapshot.
There is no continuation/pagination API in this slice.

`FeedbackPage.retrieval` reports total matches, returned count, truncation, selection
policy, and limitations. Each `FeedbackItem` and emitted `Source` also retains it
for callers using the legacy list method. This is a deterministic bounded corpus,
not a representative population sample. Aspects do not increase the feedback
denominator, and category totals can overlap because a feedback has several aspects.

`FeedbackItem.aspects` carries each imported aspect's own SQL locator, Feedback
Type, Aspect Term/Label, coarse VFC Category and Issue Type, Sentiment, signed
Sentiment Score, extraction source, Quote/status, and import timestamp. Its
references point back to the original parent feedback and its SQL locator.
`classifications` contains original **curated VFC labels only**. Its legacy
`vfc_category`/`vfc_issue` fields mean Aspect Term/Label; the separate aspect fields
mean coarse buckets. `vfc_combined` remains unknown because SQL does not store it.
Feature mappings stay unknown in this feedback-only service; the combined service
can attach exact reviewed matches from its private configuration. A coarse category
is not a canonical Feature ID.

An inferred aspect's Quote is `supported` only when it is a nonblank exact substring
of the imported Verbatim. `missing` and `mismatch` aspects remain visible with a
limitation; consumers must not present them as grounded claims. Curated aspects
use `not_applicable`. Curated VFC labels do not establish human authorship of coarse
buckets or Sentiment Scores. Scores are not confidence or ratings, and zero Neutral
scores cannot recover intensity. A feedback with zero aspects is retained.

`date`, `rating`, and `Context.as_of` stay null. `imported_at` retains `created_at`
without claiming an observation date. `since` excludes undated feedback and reports
that limitation. Existing graph-backed feedback reads also honor the additive
Engine Type/Source filters.

### Identity, scope, and missing datasets

The default source namespace is `bmw-feedback` and must be shared by the team:
`evidence:<dataset_key>:<percent-encoded Feedback Explorer ID>` identifies feedback;
`aspect:<dataset_key>:<SQL UUID>` identifies an imported aspect;
`source:<dataset_key>` identifies dataset metadata. Parent UUIDs locate SQL feedback;
aspect UUIDs locate SQL aspects. Original CSV row/file locations, source versions,
and extraction model/prompt versions are unavailable and are not invented.
Aspect UUIDs may change on reimport; SQL citations resolve the **current import**,
not an immutable historical snapshot.

The resolver accepts a read ID or its `fb:`/`kg:` wrapper and returns a typed
FeedbackItem, FeedbackAspect, FeedbackDataset, or feedback-coverage ModelNode. These are read projections,
not persisted ontology Evidence/SourceDocument/Signal objects. It does not resolve
a query hash. The virtual `vehicle:feedback:<Derivate>` IDs are likewise read
identities. The combined service reconciles them through `feedback_models` for
read contexts and model citation resolution. Persisting SQL records in a closed
graph is a separate ingestion operation.

The feedback-only live registry derives Derivates and ISO-country coverage from SQL, then groups
EU member countries under `EU` using `python/bmwow/knowledge/geography.py`.
The policy uses the [27 EU member states](https://european-union.europa.eu/easy-read_en),
verified on 2026-10-10; it is not a definition of all European markets. GB, NO, CH,
and other nonmembers retain their own region codes. Membership changes require
reviewing this explicit policy.

`ModelNode.regions`, its `data_coverage`, and `list_supported_models()` use grouped
region codes. `list_regions()["EU"].markets` contains only member countries actually
present in feedback coverage; no EU option is advertised when none are present.
An agent request for `regions=["EU"]` expands through that registry into SQL country
filters. A default request selects grouped regions once, without duplicating member
countries as separate regions. The original `FeedbackItem.market` and
`Context.country_codes` remain the individual country, preserving source scope,
citations, and per-region denominators. Country grouping makes no database writes.

The regional search locale uses the first covered country in alphabetical order;
search language defaults to English as an application policy, not a language claim
about Verbatim. Equipment, sale availability, and competitive selection remain unknown.
Registry errors propagate through the teammate's existing failure-reporting path;
empty coverage does not activate the YAML fallback.

The combined registry also includes configured source markets. A source-only `EU`
can therefore be advertised even without EU feedback; its selector remains `EU`
instead of an empty unrestricted SQL filter. Explicit configured search locales
take precedence over the feedback-only alphabetical fallback. RoW is not offered
by the initial manifest until a research locale is chosen; its sales remain readable.

From `python/`, inspect a region with this command (apply the macOS environment
prefix when needed):

```sh
uv run python -m scripts.inspect_neon_feedback --env-file ../.env --region EU --limit 50
```

The existing `--country` option still accepts individual countries or the EU alias.

On the feedback-only service, sales, studies, capabilities, portfolio, and documents raise
`KnowledgeUnavailableError` when requested. Competitive selection returns an empty
list for v1 request resolution, with availability metadata marking competitors
unavailable. Taxonomy returns `None` so v1 can use its configured product-feature
taxonomy; SQL coarse buckets are not silently substituted for that taxonomy.
Synthetic data is never mixed into this backend. `store_findings()` stays `False`.

### Persisting SQL feedback in the graph

To persist SQL feedback beyond its current read projections, hydrate a closed graph with actual source metadata,
Evidence, and reviewed interpretations. Preserve source versions, exact original
locations, scope, dates, groups, ranges, units, conditions, and provenance, then
run `validate_bundle` on the **complete** merged snapshot. SQL read DTO validation
does not replace graph validation or authenticate human review. Source revision
metadata and other datasets require coordination with their owners and a separate
approved import/migration scope. This slice creates no Neon resources or schema changes.

## Candidate acceptance and orchestration handoff

The combined snapshot/Neon read service, workbook import commands, reviewed mapping
configuration, and separate local candidate store are described in
[the implementation plan](knowledge-ingestion.md). They preserve the v1 record
contracts. A private curation manifest supplies source-specific markets and explicit
Derivate identities; missing mappings and segment decisions remain visible.

`FileCandidateStore.accept(candidate, expected_fingerprint=...)` reads the current
snapshot under an exclusive local writer lock, rejects stale writes and conflicting
payloads, validates the complete merge, and replaces the file atomically. Identical
IDs and payloads are idempotent. It rejects Requirement/Decision nodes and candidate
relationships touching existing Requirements/Decisions. It is a local persistence
primitive, not an authenticated API or a `store_findings` implementation.

`store_findings` is intentionally absent from the read service. The v1 optional
bridge returns `False`: an analysis may be saved to v1's ignored/local analysis
directory, but it is not stored in Neon or accepted into the ontology.

Situation analysis now records the optional write in `ontology_persistence`:
`skipped` when `store_findings` returns `False`, `stored` when it returns `True`,
and `failed` with an `error` when it raises. The configured hook's completion does
not establish graph acceptance or human approval. The local analysis is saved
before the hook runs, then atomically replaced with the outcome. Optional write
failures preserve the analysis and its agent reports; local save failures still fail the run.
`RunStatus` and streamed `run_finished` events expose the same outcome, including
after restart. A completed analysis can therefore be `done` with a failed optional
write. Older saved analyses load with `ontology_persistence=None` (unknown).

The next write integration must explicitly translate validated agent outputs into
candidate Signals/Needs/Trends/Assumptions with provenance and epistemic status,
validate the merged graph, and commit atomically against the expected snapshot.
SituationAnalysis and its Source records are read/analysis DTOs, not persisted
ontology objects. Requirement proposal validation and revision-specific human
Decision events remain separate. No source read or LLM finding grants approval.

Combined reads, workbook import, and local citation inspection are now available. The
feedback agent counts the imported aspects per feature, direction and region with intervals;
it does not embed or cluster Verbatim. It maps an aspect to a feature with
`FeedbackClassification.attribute` first (the curated VFC mapping), then with interim aliases
in `python/bmwow/agent/rules.yaml` for features of the active taxonomy only; filling
`attribute` on the SQL side therefore improves the mapping without agent changes. Baseline
reads typed study scores and the snapshot's sales; source-region sales routing remains
orchestration work. Curate catalog capabilities and mappings, then connect validated agent
candidates, synthesis, and the requirement dossier.

For the frontend, group by feedback identity and render its aspects underneath;
show Quote status and curated/inferred provenance separately. Retain the optional
`Source.aspects`, `Source.retrieval`, and `Source.imported_at` fields when parsing
reports. Display import time separately from the unknown feedback date. A report
can contain missing-data errors while the feedback read path remains available.

For orchestration, use `get_feedback_page()` when a zero-result selection still
needs retrieval metadata, and inspect `get_data_availability()` before planning
reads from unconnected datasets. The legacy list method carries the same metadata
on each returned feedback. Do not treat stored aspects as accepted Signals or
Sentiment Scores as extraction confidence. Validate any later graph candidate
against a complete merged snapshot.

Psycopg connection behavior follows its [transaction guidance](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)
and [parameter binding guidance](https://www.psycopg.org/psycopg3/docs/basic/params.html).
Coordinate boundary changes with both teammates rather than duplicating the
ontology models inside the agent or frontend layer.

## Verification

`python/tests/knowledge/` checks complete graph validation, copy isolation, metadata
preservation, conditional/ranged capabilities, classification grouping, explicit
country membership, zero and future/group sales, unknown study metadata, partial
dates, citation resolution, async bridge support, identity-based feedback dedupe,
and a real LangGraph run with the new backend and controlled reader nodes.
Additional tests cover workbook layouts/formula caches, exact source versions,
reviewed/proposed mappings, canonical combined identities, source-only region
selectors, superseded capability reads, idempotent merges, stale/concurrent writes,
protected requirement/review paths, and connection retry boundaries.
The graph test uses the real baseline node (facts only, no LLM step) and replaces the
other three interpretation agents with controlled readers. `test_pipeline_ontology.py`
runs the whole pipeline (all agents, validate, structure_agent, gap_fill, collect)
against the synthetic snapshot with fake LLM/search providers, checks that features
come from the ontology taxonomy and citations resolve, and that the snapshot is
unchanged. Existing v1 tests separately exercise all four agents.

Run the Python checks from AGENTS.md. They validate integration behavior, not the
merit of real BMW proposals or live provider calls. Private workbook and live Neon
checks are separate opt-in inspections; ordinary tests use synthetic sources.
