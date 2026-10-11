# Combined knowledge implementation plan

This implements the first runnable milestone from [issue #12](https://github.com/itsmeyaw/bmwow/issues/12):
one read service for a curated ontology snapshot and read-only Neon feedback.
The ontology remains v0.2.0 and the existing v1 record contracts remain unchanged.
Python modules have typed boundaries and keep I/O at the edges for the TypeScript port.
This completes the knowledge foundation, not the full requirement/review workflow
defined in [the project plan](project-plan.md#first-complete-milestone). Read
[the ontology guide](ontology.md) for object meanings and
[the data-layer handoff](data-layer.md) for consumer qualifications.

## Implementation sequence

1. **Private curation and identity.** Define canonical models, source-specific
   markets, Features, model profiles, search policies, and exact mappings in a
   `CurationManifest`. Keep G60/G68 as separate identities. Unreviewed segments,
   sale availability, competitors, and source populations remain explicit.
2. **Workbook ingestion.** Import sales as original group/market/year observations
   and studies as individual measurements. Hash the source version and retain
   cell, question, and response-category locators. Keep zeros, unknown scale/sample
   metadata, and future labels; normalized sample totals are annotations.
3. **Combined reads.** Serve graph knowledge and SQL feedback through
   `CombinedKnowledgeService`. Reconcile Derivates through explicit IDs, union
   dataset coverage without inferring sale availability, and route citations to
   their original backend. Instantiate a new service to refresh registry coverage.
4. **Reviewed mappings and catalog staging.** Reviewed study mappings create
   evidence-backed findings. Proposed mappings stay visible but do not establish
   feature associations. Accept a closed, visually reviewed catalog staging bundle;
   preserve edition, original country, variant, measurement, and package conditions.
5. **Separate candidate writes.** Merge candidates idempotently, reject conflicting
   IDs, validate the complete graph, check its fingerprint under a writer lock,
   and replace the local file atomically. Requirement and human Decision writes
   remain separate operations.
6. **Neo4j evaluation.** After the first real case works, compare persistent graph
   storage/traversal against these interfaces using the synthetic fixture.

Steps 1–5 have code and synthetic tests. Complete catalog extraction, automatic
mapping proposals, competitor research, and Neo4j persistence are subsequent work.
No SQL view, feedback relabeling, provider request, or database migration is required
by this milestone.

## Curation and import

Run from `python/`. All private inputs, configs, reports, and snapshots stay under
ignored `data/` or `raw_data/`. The commands print aggregate counts, not source records.

```sh
uv sync --locked
uv run python -m scripts.import_knowledge --config ../data/knowledge/curation.json --init-config
```

Review the generated template. It knows the supplied Derivate codes and dataset
labels, but leaves segment, model name, sale availability, and feature mappings
for team review. `EU` sales and study nodes have distinct IDs and unknown country
populations. Feedback retains the current EU member-country query policy. GB and
NO retain their country groups. CA is not silently assigned to US.

`source_markets` keys use `sales:<code>` or `studies:<code>`. A source-only query
region retains its explicit selector instead of an empty worldwide feedback filter.
RoW needs an explicit research locale before it appears in the v1 region selector;
its sales observations are still readable. Search locale is application policy,
not a claim about a dataset's country population.

Add canonical Feature nodes with reviewed definitions and allowed ontology domains,
then set `knowledge.feature_keys`. Original labels map through `vfc_mappings`,
`study_mappings`, or `aspect_mappings` with `feature_id`, `status`, and `rationale`.
SQL VFC mappings may use exact Aspect Terms because the original combined string
is absent. `get_aspect_mapping()` exposes separate mapping metadata without
rewriting imported aspects. Matching coverage and reviewer accuracy are separate
metrics; agreement with an LLM does not establish label correctness.

```sh
uv run python -m scripts.import_knowledge \
  --config ../data/knowledge/curation.json \
  --input-dir ../raw_data \
  --output ../data/knowledge/snapshot.json \
  --report ../data/knowledge/import-report.json \
  --as-of 2026-10-11
```

The output includes `snapshot.config.json`, with generated combined-sales group
identities. The optional private report retains questions requiring mapping review.
The importer rejects changed headers, invalid values, and formulas without cached
results. Repeat imports with the same files/config/as-of produce identical source
identities. A changed file is a new source version; choose which observations are
current through reviewed revisions, never by overwriting the originals.

For a reviewed catalog slice, add `--catalog-bundle <private-path>`. The staging
bundle must be closed, share the curated context identities, and pass graph
validation. Conflicting context payloads require reconciliation in the manifest.
A German catalog remains a German claim; a source's European sales label does not
expand catalog availability. Table symbols, column alignment, and footnotes must
be visually verified before staging. This importer does not parse arbitrary PDFs.
`--catalog-bundle` can be repeated (for example a catalog slice and a competitor bundle).

### Competitors and their values

`bmwow/knowledge/competitors.yaml` lists competitor models (public information):
segment, powertrains, sold regions, and the BMW models they compete with.
`scripts/stage_competitors.py` turns it into VehicleModel nodes, model profiles (written
into the curation file), and `COMPETES_WITH` edges. With `--analysis <run>.json`, it also
stages the competition agent's web-extracted values: each one becomes Evidence
(`web_excerpt` holding the verbatim quote with the number), a `competitor_capability`
Signal (measurement, variant, and engine type in `context.engine_types`), and a `CONCERNS`
edge to its Feature. Provenance marks them as machine extractions that no human has
reviewed. Review the `--list` output before importing. Stored values are read back
through `get_attribute_values`, so later runs reuse them instead of extracting them again.

```sh
uv run python -m scripts.stage_competitors --curation ../data/knowledge/curation.json \
  --analysis ../data/processed/analyses/<run_id>.json \
  --output ../data/knowledge/competitors.staging.json --list
```

`AttributeValue.variant` passes on the capability's variant. Catalog and competitor
staging set `context.engine_types` (`bev`, `phev`, `ice`), so values are only compared
within one powertrain.

### Proposed feedback mappings

Feedback aspects carry `attribute` and `mapping_status` from the curated term mappings
(`vfc_mappings` for VFC labels, `aspect_mappings` for LLM-extracted terms). By default,
only reviewed mappings set `attribute`. Set `knowledge.accept_proposed_mappings: true`
in the curation to let proposed mappings feed features too. Their `mapping_status` stays
`proposed`, so consumers can label them. Leave it off for any reviewed deliverable.

## Inspect and connect

```sh
PYTHON_DOTENV_DISABLED=1 uv run python -m scripts.inspect_combined_knowledge \
  --snapshot ../data/knowledge/snapshot.json \
  --config ../data/knowledge/snapshot.config.json \
  --env-file ../.env --model G60 --region EU
```

This resolves the real brief, reads bounded feedback plus sales/studies, and checks
citations without LLM, embedding, or web calls. It reads only DATABASE_URL from the
chosen env file. Connection establishment retries transient failures twice by
default; authentication and query errors are not replayed.
See [Neon's connection disruption guidance](https://neon.com/docs/manage/endpoints/).

The analysis CLI accepts `--snapshot`, `--knowledge-config`, and `--env-file`.
Add `--resolve-only` to inspect the brief without running interpretation agents.

```sh
PYTHON_DOTENV_DISABLED=1 uv run python -m scripts.run_analysis scripts/example_request.json \
  --snapshot ../data/knowledge/snapshot.json \
  --knowledge-config ../data/knowledge/snapshot.config.json \
  --env-file ../.env --resolve-only
```

Provider-enabled analysis remains subject to the BMW data boundary in the project
plan. Startup code may call `create_knowledge_service(...)` and then
`configure_service(...)`; no orchestration module changes are needed.
The factory requires a live SQL feedback connection (or an explicit test repository)
and captures coverage at construction; rebuild the service when that registry changes.
Its snapshot contains graph data only, while SQL feedback citations resolve the
current import through read projections.

The aggregate inspector requests sales/studies by source region explicitly.
The v1 baseline still queries sales with `brief.markets`. When these are feedback
countries, they cannot select a source Europe total with unknown country membership.
Routing that additional regional context into analysis is still orchestration work.
Typed study reads are available, but no complete deterministic study-analysis agent
is supplied by this milestone.

`FileCandidateStore.accept(candidate, expected_fingerprint=...)` is a local backend
write primitive, not an authentication boundary and not a `store_findings` adapter.
The orchestration owner must translate validated findings into candidates before
connecting that optional hook. It cannot submit Requirements or human Decisions.
It also rejects candidate relationships touching existing Requirements/Decisions;
authenticated review and requirement proposal persistence need separate operations.
Snapshots and matching configs should be published together while readers are
stopped; candidate writes only update the snapshot and preserve config identities.

## Validation

Synthetic tests cover workbook layouts, proportions, unknowns, explicit zeros,
combined sales, source-version identity, reviewed/proposed mappings, citation
routing, copy isolation, stale writes, invalid evidence, competing writers,
connection retry boundaries, and the existing v1 bridge. Current capability reads
exclude superseded revisions while the full snapshot retains history.

Run all Python checks from `AGENTS.md`. Real import checks run locally and emit
aggregate summaries. Do not put private snapshots or reports into GitHub or CI.
`openpyxl` is an XLSX reader dependency; SheetJS is a TypeScript counterpart for
the eventual port. The parsers' mapping rules and synthetic fixtures define parity.
Neo4j has no driver, schema, or deployment in this implementation. Evaluate it later
against the same read/validation boundaries once the first complete case demonstrates
the graph persistence and traversal requirements.
