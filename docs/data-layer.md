# Knowledge layer and orchestration v1 handoff

`bmwow.knowledge` supplies typed reads from either a validated ontology v0.2.0
snapshot or the existing private Neon feedback tables. The synthetic demonstration
uses only the invented fixture; the Neon backend serves feedback and aspects only.
Other SQL datasets and ontology writes remain pending. The raw-data adapter and
ontology contracts are unchanged.

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
sales with their original qualifications. Synthetic setup is explicit: the factory
rejects any snapshot containing a non-synthetic SourceDocument.

If `import bmwow` fails on macOS, see the troubleshooting note in
[`python/README.md`](../python/README.md).

## Boundaries and ownership

- `python/bmwow/ontology/` remains the source of truth for graph objects,
  relationships, validation, and generated JSON contracts. Its version stays 0.2.0.
- `python/bmwow/knowledge/records.py` defines **read projections**, not additional
  graph node types. It reuses ontology Context, Locator, Measurement, and NumericRange.
- `repository.py` defines `SnapshotRepository.load_snapshot() -> GraphBundle`.
  `InMemoryRepository` validates a complete snapshot and returns isolated copies.
- `feedback.py` defines the query-based `FeedbackRepository` port and the partial
  `FeedbackKnowledgeService`. It does not wrap SQL feedback in an invented graph.
- `neon.py` implements that port with Psycopg 3 against `public.feedback_entries`
  and `public.feedback_aspects`. Each operation owns a short read-only transaction.
- `service.py` provides deterministic reads over one fixed, validated snapshot.
  Construct and inject a new service when the dataset version changes. Read results
  and configuration are copies; consumers cannot mutate the stored graph.
- `config.py` holds explicit application curation: segment profiles, sale regions,
  market search locales, feature keys, reviewed VFC mappings, and combined sales
  group labels. It does not guess missing product metadata.
- `synthetic.py` supplies invented configuration for the tracked fixture only.
- `bmwow.agent.models.knowledge` reexports the read models for v1 imports.
  `bmwow.agent.knowledge_bridge` is a thin temporary v1 compatibility boundary.

All Python dependencies, including the LangChain/LangGraph, OpenAI, Firecrawl,
SQLite checkpoint, and clustering integrations, are declared and locked in
`python/pyproject.toml`. Tests use fake LLM/search providers; installing these
integrations does not call them.

## Inject the service

The application startup code owns configuration, storage, and injection:

```python
from bmwow.knowledge import KnowledgeService
from bmwow.agent.knowledge_bridge import configure_service

# repository and config are supplied by the application, not created by the agents.
configure_service(KnowledgeService(repository, config))
```

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

The Neon backend supplies registry, model metadata from feedback coverage,
feedback/aspects, retrieval metadata, and SQL citation resolution. Optional bridge
methods `get_feedback_page()` and `get_data_availability()` expose the bounded
selection and connected dataset kinds. Snapshot backends return `None` for these
optional additions; existing `get_feedback_items() -> list[FeedbackItem]` stays intact.

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

`NeonFeedbackConfig` controls dataset namespace, default/hard limits and timeouts.
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
Feature mappings stay unknown; a coarse category is not a canonical Feature ID.

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
identities; reconcile them explicitly with canonical VehicleModel IDs on ingestion.

The live registry derives Derivates and ISO-country coverage from SQL, then groups
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

From `python/`, inspect a region with this command (apply the macOS environment
prefix when needed):

```sh
uv run python -m scripts.inspect_neon_feedback --env-file ../.env --region EU --limit 50
```

The existing `--country` option still accepts individual countries or the EU alias.

Sales, studies, capabilities, portfolio, and documents raise
`KnowledgeUnavailableError` when requested. Competitive selection returns an empty
list for v1 request resolution, with availability metadata marking competitors
unavailable. Taxonomy returns `None` so v1 can use its configured product-feature
taxonomy; SQL coarse buckets are not silently substituted for that taxonomy.
Synthetic data is never mixed into this backend. `store_findings()` stays `False`.

### Later graph ingestion

For future ontology storage, hydrate a closed graph with actual source metadata,
Evidence, and reviewed interpretations. Preserve source versions, exact original
locations, scope, dates, groups, ranges, units, conditions, and provenance, then
run `validate_bundle` on the **complete** merged snapshot. SQL read DTO validation
does not replace graph validation or authenticate human review. Source revision
metadata and other datasets require coordination with their owners and a separate
approved import/migration scope. This slice creates no Neon resources or schema changes.

## Write path and next milestone

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

Feedback reads and local citation inspection are now available. The orchestration
owner should next choose how to use imported aspects and stored embeddings: the
current feedback agent still embeds the selected Verbatim and interprets clusters.
This adapter neither uses nor re-creates embeddings. Then connect studies, sales,
and PDF capabilities, followed by candidate ingestion, synthesis, and the dossier.

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
The graph test uses the real baseline node; its positioning LLM step and the other
three interpretation agents are replaced with controlled readers. Existing v1
tests separately exercise all four agents with fake LLM/search providers.

Run the Python checks from AGENTS.md. They validate integration behavior, not the
merit of real BMW proposals, actual SQL ingestion, or live provider calls.
