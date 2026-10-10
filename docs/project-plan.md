# BMWow project plan

The deliverable is a working product decision assistant: a product manager selects
a BMW baseline and target market, inspects customer needs, receives justified and
prioritized successor requirements, and challenges, edits, approves, or rejects
them. Evidence, assumptions, uncertainty, and conflicting findings stay visible.
The planning horizon is three to five years and the output is customer-facing.

Ontology v0.2.0 supplies the common contract. It is not the finished application.
Keep that contract stable while building the first complete workflow; extend it
when an actual source mapping or product question exposes a gap.

## BMW data boundary

BMW has prohibited uploading its data to GitHub. This applies to private as well
as public GitHub repositories. Commit source code, configuration, contracts,
documentation, migrations, and wholly synthetic fixtures. Keep original files,
real excerpts, database contents/dumps, derived datasets, embeddings, cached
research packs containing BMW content, generated requirements based on private
records, screenshots of records, and data-bearing logs/transcripts out of GitHub.

Use the existing ignored `raw_data/` for local private input and derived snapshots.
Local database files are ignored too. Teammates obtain originals through BMW's
permitted sharing channel or use an access-controlled server database. Commit
import scripts and migrations, but not the database contents. CI and shared
frontend examples use synthetic data. Real input must not enter GitHub build
artifacts, test reports, caches, or issue/PR text.

Entire captures sessions in separate Git refs. Every teammate must run
`entire configure --local --skip-push-sessions` before pushing this project.
Ignored transcript files alone do not prevent checkpoint uploads. Avoid pushes
of checkpoint refs or `entire/*` branches. Inspect staged content before each push;
ignore rules can be bypassed and do not remove already tracked content.

On 2026-10-10, the local inspection found no tracked BMW spreadsheet/PDF files,
no `raw_data/` paths in locally available ordinary branch/remote history, and
`push_sessions: false` for this clone. This is not a certification of all remote
history or of every teammate's clone.

The team has selected Neon for shared PostgreSQL storage, based on its current
understanding that a private server database is allowed. Keep access controlled
and database contents outside GitHub. A local snapshot can support development
while the database is prepared. This does not establish permission for hosted
LLM APIs; confirm that boundary before wiring private data to model calls. Public
web research queries use public topics and do not contain original private BMW text.

## Shared database: Neon

Neon is the chosen storage provider. Provisioning, migrations, imports, and the
application connection remain to be implemented; this decision does not mean a
database has been created or BMW data uploaded.

- Use one team project and designate one shared dataset as the canonical source
  for integration and the demo. Agree its project, branch, and database identity
  so teammates do not accidentally connect to different datasets.
- Assign an owner for imports and schema migrations. Preserve stable source IDs,
  use idempotent imports, and record dataset/import versions and counts. Sharing
  a database alone does not prevent duplicate records or conflicting changes.
- Raw tables may retain the supplied spreadsheet layout. A Python adapter maps
  those rows and verified PDF passages into the existing ontology contract. Keep
  original PDFs/workbooks in BMW-permitted file storage and preserve their locators.
- Agents and frontend consumers use backend operations for validated proposals
  and human decisions. The service checks complete merged snapshots and commits
  accepted changes atomically. Keep database credentials on the server; the browser
  receives authorized application payloads.
- Use `DATABASE_URL` for pooled application connections and
  `DATABASE_URL_UNPOOLED` for direct migration connections. Keep values in ignored
  local environment files or deployment secrets, never committed configuration or
  `NEXT_PUBLIC_*` variables. GitHub CI uses synthetic data and a separate test store.
- The repo currently includes Drizzle and `@libsql/client`. Drizzle can remain the
  migration tool if that is the SQL owner's choice; the SQLite/libSQL driver cannot
  connect to Neon. Select a PostgreSQL driver/configuration when implementing the
  adapter, and coordinate dependency and lockfile changes with that owner.

See [Neon connection guidance](https://neon.com/docs/connect/choose-connection),
[connection pooling](https://neon.com/docs/connect/connection-pooling), and
[Drizzle with Neon](https://orm.drizzle.team/docs/connect-neon).

## First complete milestone

Demonstrate one model, one target market, and one customer theme. A useful starting
candidate is G70 / United States / seat cooling and comfort. It combines feedback,
study findings, existing equipment, and a reported competitor comparison. Validate
the case during ingestion; this choice does not assert it is the highest-priority
theme in the full dataset.

The German July 2026 catalog is a qualified reference. It does not prove US
availability or the equipment fitted to a feedback author's vehicle. Keep those
gaps visible in the baseline rationale, scope-transfer explanation, and assumptions.

The milestone is complete when the app can:

1. Retrieve deduplicated comments, relevant study cells, sales context, and verified
   catalog passages with stable IDs and original locators.
2. Produce a grounded customer need and explicit applicability/future assumptions.
3. Propose a customer-facing requirement with change intent, a qualified baseline,
   acceptance criteria, justification, opposing evidence, and priority rationale.
4. Show that dossier in the frontend and record a product manager's decision.
5. Revise the proposal without carrying approval forward to the new revision.

A small validated file snapshot can support this milestone before SQL integration
is ready. The final workflow should use the same contract through a database
adapter. The shareable demo and CI remain runnable with synthetic content.

## Implementation sequence

1. **Private ingestion and data adapter.** Preserve raw SQL/CSV column layouts as
   needed. Map records into SourceDocument and Evidence with source versions,
   original locators, classifications and scope. Deduplicate feedback by original
   record identity. Preserve survey means versus shares and combined-model future
   sales. Start PDF mapping with a few visually verified relevant pages and footnotes.
   Validate the complete resulting snapshot and report unresolved mappings.
2. **Signals and customer needs.** Use typed extraction outputs to separate original
   records from interpretations. Group findings into needs while retaining opposing
   findings, uncertainty, and explicit scope. Persist candidate Signals, Needs,
   Trends, and Assumptions through a separate validated candidate-ingestion path.
3. **Requirement synthesis and prioritization.** Bind the existing ontology tools
   to LangChain. Requirements reference the existing findings/needs/assumptions;
   `validate_proposal` handles one Requirement and links, not arbitrary ingestion.
   Explain priority using customer value, evidence breadth, recurrence, market
   relevance, and uncertainty. Keep extraction confidence separate from importance;
   avoid treating classification rows as people or multiplying complaints by sales.
4. **Review API and frontend.** Agree payloads and ownership before wiring services.
   Provide model/market selection, needs, requirement list and dossier, source
   inspection, and review/edit/priority actions. Persist authenticated human Decision
   events for exact revisions. The service owns atomic writes and stale-snapshot checks.
5. **External research.** Add a bounded public-sentiment, competitor and trend research
   pack to the working case. Capture originals, dates, locators, source independence
   and limitations. Begin with a reproducible cached pack; add live fetching once the
   evidence and review flow works. Manufacturer claims and owner experiences stay distinct.
6. **Broaden and rehearse.** Extend to additional themes and a representative set of
   requirements, then another model/market if time permits. Exercise conflicting
   evidence, missing data, unavailable sources, and revision-specific decisions.
   Prepare a reproducible demo, fallback synthetic dataset, and clear narrative.

Web research can run in parallel with the initial workflow. It should enrich an
already inspectable reasoning chain rather than delay the first functioning case.

## Team boundaries

- **Data/ontology owner:** input mappings, source identities, private ingestion,
  graph validation, and the adapter around the teammate's SQL schema.
- **Orchestration owner:** typed extraction and synthesis, tool bindings, bounded
  research, proposal generation, and explainable priority recommendations.
- **Frontend owner:** synthetic-contract development, model/market selection,
  requirement dossiers, source views, and human decision/edit interactions.

Coordinate stable IDs, API payloads, storage ownership, proposal lifecycle, and
data-sharing rules. These boundaries can be covered by three people; a separate
data teammate is optional. An agreed backend service exposes ontology operations
so the frontend and agents do not independently implement graph rules.

## Verification and demo evidence

Keep contract tests and synthetic integration tests in Git. Check real ingestion
locally: source counts, duplicate identities, question/response labels, PDF columns
and footnotes, scope, time labels, and traceable chains. Human-check a small set of
proposals for unsupported statements and persuasive justification; schema validation
does not establish product merit.

Demonstrate the difference between a new feature and an improvement to an existing
one, why priority differs across proposals, and how contradictory evidence or a PM
edit changes the recommendation. A large number of agents or a comprehensive
configuration engine is not an acceptance criterion.

See [ontology guide](ontology.md), [ontology implementation plan](ontology-plan.md),
[source mappings](../contracts/ontology/source-mappings.json), and
[web research contract](web-research.md).
