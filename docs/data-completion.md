# Raw data to the agent boundary

This workflow prepares reproducible, qualified evidence for the knowledge read
service. It does not run interpretation agents, create Requirements, or record
authenticated review Decisions. Inputs, exported CSVs, review files, snapshots,
and reports remain in ignored local directories. CLI summaries contain aggregate
counts; original labels and source text remain in the private files.

## Export and version feedback

From `python/`, export the supplied feedback XLSX layout:

```sh
uv run python -m scripts.export_feedback --input-dir ../raw_data --output-dir ../data/feedbacks
```

The exporter retains every classification row, exact text, blank labels, and
Feedback Types. A reserved `__bmwow_origin` column records the original workbook
hash and worksheet/range. Invalid headers and uncached formulas fail before
replacing an existing CSV. Standalone CSV imports receive their own file hash and
CSV row locator; they cannot recover an original workbook locator.

At the repository root, explicitly apply the additive migration on an approved
development database, then import without enrichment:

```sh
pnpm preprocess --no-enrichment --migrate --env-file data/development.env
pnpm preprocess --no-enrichment --env-file data/development.env
```

The env file needs `DATABASE_URL`; `--migrate` additionally requires a direct
`DATABASE_URL_UNPOOLED`. Migrations are never implicit. Test shared migrations on
an isolated database/Neon branch before applying them to the shared service.
`--csv-dir`, `--taxonomy-file`, and `--limit` select the input scope.
The importer defaults to 25 pooled connections, matching its bounded feedback
concurrency. `--concurrency` accepts 1–100 to match the selected database's capacity.
Legacy embeddings are read only when archiving their individual rows;
without processing provenance they are never downloaded for reuse.

`feedback_revisions` stores an immutable payload with original rows, classifications,
source locators, source/text/input hashes, processing signature, enrichment/prompt
versions, embedding specification, and the resulting aspects. Current
`feedback_entries` and `feedback_aspects` remain the query projection. Resume compares
input and processing hashes, including the effective taxonomy; an embedding alone
does not mark work complete. A changed text, classification, source edition, mapping,
or processing version refreshes the projection transactionally while keeping history.
Unchanged versions are skipped, including imports with null embeddings. An advisory
lock and expected revision check reject competing stale writers. Historical replay
uses its archived enrichment and timestamps.

The first refresh of a pre-versioning row archives its existing database projection,
including inferred aspects, aspect identities, timestamps, and embeddings, in the
same transaction. That archive explicitly records unknown original files and
provider versions; it cannot reconstruct workbook provenance. Failed refreshes
roll back both the archive and projection. Historical citations remain readable,
but an archive without original source locators cannot satisfy selected-case readiness.

`--no-enrichment` preserves curated classifications with null intensity scores and
embeddings. Unlabelled feedback remains available with zero inferred aspects.
Provider mode uses the existing OpenAI enrichment and embedding path only when BMW
data use with the provider is authorized. Compatible embeddings are reused for
mapping-only refreshes. New taxonomy suggestions go to ignored
`data/feedbacks/taxonomy-proposals.json` (override with `--proposals-file`); they
must be reviewed before entering the effective taxonomy. Unmapped buckets remain
`Unclassified`. Failure IDs are written only to a private local report.

## Curate one model, market, and theme

Initialize and import the workbooks using the existing
[knowledge ingestion workflow](knowledge-ingestion.md). Then prepare exact mapping
suggestions:

```sh
cd python
uv run python -m scripts.prepare_curation --config ../data/knowledge/curation.json --feedback-dir ../data/feedbacks --import-report ../data/knowledge/import-report.json --output ../data/knowledge/curation-review.json
```

The initial theme is seat comfort, with a separate seat ventilation Feature.
Lexical matches are suggestions: overall comfort, heating, massage, front/rear
seating, and ventilation must not be equated automatically. Review canonical
definitions, the selected model profile, and exact source labels. Approved mappings
use `status: reviewed`, a rationale, `reviewed_by`, and `reviewed_at`. Legacy mapping
configs remain readable without the new audit fields. Proposed mappings stay visible
without establishing a Feature association. Reimport studies after approved mapping
changes so their evidence-backed findings match the config. Unknown metadata remains
explicit; unrelated curation decisions can remain pending.

Delegated software review can additionally supply `review_provenance`, using the
existing ontology `Provenance` type. Record `actor_type: software`, `method:
llm_extraction`, the actual model/revision and prompt version, and the matching
reviewer/time. Delegation does not establish human source inspection. The combined
feedback projection exposes `mapping_provenance` alongside the mapping rationale.
Keep original source inputs, local model outputs, and decision receipts in ignored
storage. When private sources must remain on the machine, use an offline local
runtime with network access denied; no hosted extraction or embedding calls are implied.

## Review catalogs locally

```sh
uv run python -m scripts.review_catalog prepare --source ../raw_data/G70_OptionList.PDF --output ../data/knowledge/catalog-review.json
```

The parser produces page-addressed text candidates, all proposed and with unknown
availability. Its `--theme` regular expression can select other slices. Open the
original PDF beside the review file. Review edition, country, model/variant columns,
symbols, dependencies, and footnotes. Enter a precise statement, Feature, availability,
variant, conditions, measurement only if reported, and notes. Each accepted claim
requires a reviewer, timezone-aware time, rationale, and explicit visual, scope, and
conditions checks. Reject ambiguous/unrelated candidates or leave them proposed.
Extraction cannot verify table semantics or widen a German catalog to US availability.
Scanned PDFs without usable text require a separate permitted transcription/OCR workflow.

For review without sending private sources to a model or editing JSON, prepare an
offline browser form:

```sh
uv run python -m scripts.prepare_local_review --config ../data/knowledge/curation-review.json --catalog-review ../data/knowledge/catalog-review.json --output ../data/knowledge/local-review.html
```

Open that HTML file in a local browser. It embeds the original PDF locally and
blocks network calls. Review model metadata, canonical definitions, exact mappings,
and each catalog page. Enter a reviewer ID and source-based rationale for each
reviewed item. Editing a reviewed claim, catalog scope, or canonical definition
returns affected associations to proposed. Download the reviewed configuration,
catalog decisions, and private definition review receipt into ignored storage.
The form never writes or accepts the graph; pass its downloaded JSON files to the
normal staging/import commands. It has no autosave, so download decisions before
closing it. The generated HTML contains private data and must never be committed.

```sh
uv run python -m scripts.review_catalog stage --review ../data/knowledge/catalog-review.json --config ../data/knowledge/curation-review.json --output ../data/knowledge/catalog-staging.json --as-of 2026-10-11
```

Staging rechecks the source hash and exact quote on the original page, then validates
a closed SourceDocument → Evidence → product-capability Signal → Feature graph.
Human or explicitly recorded software interpretation provenance and source-country
qualifications travel with the claim. Software review requires actual visual
inspection of rendered pages, all three source checks, a model and prompt version,
and reviewer/time consistency. It passes the same hash, exact-quote, scope and
graph gates. Software attribution remains software; it does not create a human
Decision or authenticated acceptance. Package item references require matching reviewed CatalogItems in the
review's `catalog_items` with a reviewed describing claim; unresolved dependencies can use explicit `unknown`
conditions. A CatalogItem's provenance must match one of its describing claims.
The staging CLI does not accept arbitrary unreviewed availability
inferences. Merge staging with `import_knowledge --catalog-bundle`, or use the
existing `FileCandidateStore.accept` with the current snapshot fingerprint for
atomic local acceptance. Candidate writes are not an authentication boundary.

`pypdf[crypto]` handles local PDF text and AES-encrypted sources; `fonttools` supports
the supplied embedded font encodings. PDF.js (`pdfjs-dist`) includes the corresponding
PDF/crypto/font reading capabilities for a future TypeScript port. No TypeScript
knowledge modules are claimed as ported by this workflow.

## Inspect readiness before handing off

```sh
PYTHON_DOTENV_DISABLED=1 uv run python -m scripts.inspect_data_readiness --snapshot ../data/knowledge/snapshot.json --config ../data/knowledge/snapshot.config.json --env-file ../data/development.env --model G70 --region US --feature seat_comfort --feature seat_ventilation --limit 5000 --output ../data/knowledge/readiness.json
```

This command imports no agent modules and makes no LLM, embedding, or web calls.
It validates the complete graph and reports matching versus selected feedback,
truncation, version coverage, text duplication, distinct feedback with mapped/theme
aspects, mapping and quote statuses, study mapping coverage, missing datasets,
catalog scope, and unresolved citations. Aspect counts and feedback counts have
separate denominators. Counts do not measure mapping accuracy. Repeated text does
not collapse separate feedback identities or imply clustering noise.

Sales/studies use explicit source-region selectors; `--sales-region EU` can inspect
the source Europe grouping without expanding it to feedback-country membership.
Future labels, combined-model rows, zero values, and missing population/sample
metadata remain qualified. Readiness is false while required selected-scope data,
theme mappings, model metadata, or citations are missing. A connected catalog from
another country remains reference context rather than a target-market capability.
The default `--catalog-scope-policy target_market` requires catalog coverage in the
selected region. For the project plan's qualified German catalog reference, use
`--catalog-scope-policy qualified_reference`. This still requires a reviewed theme
claim with a known original scope and valid citations. The report records
`catalog_theme_coverage: reference_only`, leaves target-market availability unknown,
and requires explicit applicability assumptions for interpretation. This policy does
not change any claim's country scope, availability, or graph evidence. Missing or
unreviewed catalog claims fail either policy.

The combined read projection adds `feature_id`, `attribute`, mapping status and
rationale to aspects without replacing original labels. New feedback references
use `feedback_revision:<dataset_key>:<UUID>`; the resolver reconstructs their
archived payload even after refresh. Historical aspect UUIDs also resolve from the
archive. Logical `evidence:<dataset_key>:<Explorer ID>` citations continue to resolve
the current import. Legacy records lacking provenance remain readable and are
reported as unversioned; migration alone cannot recover their original files.

## Verification

Run all checks in `AGENTS.md`, plus `pnpm test:imports`. The default Node tests are
provider/database-free. To exercise transactions, supply `BMWOW_TEST_DATABASE_URL`
pointing to an **empty disposable database** with pgvector available; the integration
test refuses a database that already contains `feedback_entries` and never uses
`DATABASE_URL`. It tests refresh, stable parent identity, historical replay,
idempotence, stale writes, and rollback. Python synthetic tests cover original
workbook rows, pinned/history reads, exact catalog quotes, explicit visual review,
country scope, complete-graph acceptance, and readiness denominators.
