# BMWow: from customer voice to successor-vehicle requirements

BMWow is an EHL Munich hackathon project for the BMW challenge. For one car (for example the
G60 5 Series) and one or more regions (EU, US, CN), it combines customer feedback, studies, sales
data, competitor specifications and market trends into **traceable, quantified requirement
candidates** for the successor model. A product manager (PM) then reviews, constrains and approves
them.

The result is not a chatbot summary. Every number is computed by code, every claim cites its
source, and the PM has the final say.

## Contents

- [Highlights](#highlights)
  - [LLMs handle language; code handles numbers and checks](#llms-handle-language-code-handles-numbers-and-checks)
  - [Ontology and traceability](#ontology-and-traceability)
  - [The PM stays in the loop](#the-pm-stays-in-the-loop)
  - [Dashboards with a grounded chat](#dashboards-with-a-grounded-chat)
  - [Region-aware by design](#region-aware-by-design)
  - [Data boundary](#data-boundary)
- [Architecture](#architecture)
- [Quick start](#quick-start)
  - [Without BMW data or API keys](#without-bmw-data-or-api-keys)
  - [Full setup with data](#full-setup-with-data)
  - [Web research backends](#web-research-backends)
- [Limitations and next steps](#limitations-and-next-steps)
- [Development](#development)
- [Docs](#docs)
- [Data and sharing](#data-and-sharing)

## Highlights

### LLMs handle language; code handles numbers and checks

The pipeline combines LLMs with statistics, structured domain knowledge and product-management
methods. Each part does what it does best:

| Step                   | LLM                                                                | Code                                                                                                                                                          |
| ---------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Feedback preprocessing | extracts aspects from each verbatim and scores their intensity     | normalises and deduplicates rows, sets the sentiment sign from the issue type, maps 227 raw labels to about 16 categories, embeds texts for search using tokenizer and semantic search tsvector for exact text search            |
| Customer signals       | groups free text into sub-themes when aspect terms are too generic | counts distinct items per feature, direction and region (k of n), computes Wilson 95% intervals, flags thin samples, and tests each region against the others |
| Priority ranking       | none                                                               | reach × severity per category in SQL, a transparent heuristic                                                                                                 |
| Competitors            | reads values from spec pages, with a verbatim quote                | verifies the quote and number, then compares only like for like (same unit, test standard, powertrain and region)                                             |
| Trends                 | researches technology, regulation and market trends on the web     | counts independent sources; a single-source trend is marked thin                                                                                              |
| Assessment             | judges each feature against a fixed rubric, citing evidence ids    | guard rules re-check the judgment, allow one revision, then flag it; a flagged feature never becomes a requirement                                            |
| Requirements           | words the statement                                                | sets targets by rule (competitor median, best in class or today's value) and leaves them to the PM when no comparable number exists                           |

The assessment rubric follows product-management practice in the spirit of the Kano model:

- **Underperformance:** a comparable benchmark shows we trail competitors.
- **Gap:** an unmet customer need, shown by problems, requests or trends.
- **Must-have:** customers complain, but competitors are no better.
- **Strength:** we lead, or customers praise the feature.
- **Unclear:** too little evidence.

### Ontology and traceability

A typed ontology (`docs/ontology.md`, v0.2.0) defines vehicle models, features, measurements,
competitors, evidence, requirements and human review as objects with directed, validated links. A
validator checks complete evidence chains before any proposal is accepted. Every stored finding,
judgment and requirement keeps the ids of its sources: a feedback item, a catalog row, a study cell
or a quoted web sentence. The dashboard and chat show them as citations such as `[REQ-1]` and
`[G60-0042]`.

### The PM stays in the loop

At the end of the pipeline, a review gate pauses the run (LangGraph `interrupt`) and lets the PM
act on each requirement candidate:

- `approve` / `reject` with a reason
- `freeze` (keep today's value), `cap` / `floor` (bound the target), `set` (exact value),
  `deprio` (lower the priority). Code then recomputes the target, intent and priority.
- `say "REQ-2 not important; REQ-1 max 520 km"`: free text that an LLM turns into structured
  constraints. They only apply after the PM confirms them.
- `why REQ-1 ...`: an answer drawn only from that candidate's own evidence

Decisions are kept with the run. The gate runs in the terminal today (see the quick start below).

### Dashboards with a grounded chat

The Next.js app has two views:

- **`/analysis`:** what to improve first. It ranks feedback categories by priority per car, country
  and engine type, with the strongest verbatims as evidence.
- **`/situation`:** requirement recommendations. It shows one stored pipeline run per car and region
  (or all regions): each feature's assessment, customer shares with intervals, competitor
  comparison, trends, and the requirement with its target options.

A chat panel on both views answers questions about the page you are on. It only uses that page's
run and feedback data, through tools: hybrid search over verbatims (pgvector + full text, fused with
RRF), the rankings and the stored runs. It cites the ids it used and never computes new shares or
targets. A separate web-search tool can add market signals. Only a short public topic leaves the
app; customer text never does. The chat reports web signals separately from customer evidence and
does not change stored data.

### Region-aware by design

Each run covers specific regions. Feedback and sales are filtered by that region's markets, and
competitors by where they are sold. Web searches use the region's locale. The number of analysed
features therefore differs between EU, US and All. Each region has different customer topics,
different competitors and different data. A pooled "All" run can also confirm a feature that is too
rare in any single region.

### Data boundary

BMW data never leaves BMW-permitted storage: not to GitHub, not into fixtures, not into web
queries. LLM steps that would send internal feedback text are off unless
`ALLOW_LLM_ON_INTERNAL_DATA=true`. Tests, CI and the demo use synthetic data only.

## Architecture

```text
 Feedback CSVs ──► preprocess.ts (LLM aspects + embeddings) ──► Neon Postgres + pgvector
 Sales / study workbooks, catalog ──► knowledge layer (ontology snapshot) ──┐      │
                                                                             ▼      ▼
 AnalysisRequest (car, regions) ─► resolve ─► baseline ─┐
                                              competition ┤ (parallel)
                                              feedback ───┤──► validate ─► structure_agent ─► candidate_agent ─► PM gate
                                              trends ─────┘     (packages, rubric judgment,   (requirements,     (approve,
                                                                 guard; gap_fill round)         targets)           constrain)
                                                                                                      │
                                                     export_analysis.py ─► analysis_* tables ─► /situation dashboard + chat
```

- **App (TypeScript):** one Next.js app is both frontend and backend. The UI is in `src/app/` and
  `src/components/`. Route handlers are in `src/app/api/`, and server-only logic is in
  `src/server/`.
- **Pipeline (Python):** `python/bmwow/{ontology,knowledge,agent}` is the reference implementation
  (LangGraph). Modules are later ported to `src/server/` under the same names.
- **Contracts:** `contracts/ontology/` is shared by both languages. It is generated from the Python
  ontology models.

```text
src/app/(dashboard)/   /analysis and /situation pages
src/app/api/chat/      chat endpoint; logic in src/server/chat/
src/server/            server-only reads (analysis/, situation/), DB schema, chat agent and tools
scripts/               preprocess.ts (feedback → Neon), import-sales.ts
migrations/            SQL DDL, source of truth for the Neon schema (incl. analysis_* tables)
contracts/ontology/    generated schema, vocabulary and agent contracts; synthetic fixture
python/bmwow/agent/    pipeline nodes, rules.yaml (thresholds, rubric), prompts/, tools/
python/scripts/        run_analysis, review_requirements (PM gate), export_analysis, build_web_corpus
docs/                  guides (listed below)
data/, raw_data/       local BMW inputs and caches; gitignored, never committed
```

## Quick start

You need Node with the pnpm version from `package.json`, and Python 3.12 with
[uv](https://docs.astral.sh/uv/).

### Without BMW data or API keys

These run on synthetic data with fake LLM, web and knowledge services:

```sh
cd python && uv sync --locked
uv run pytest                                          # pipeline, statistics, ontology, export

# The full pipeline and the interactive PM gate.
# Try: list · show REQ-1 · why REQ-1 · cap REQ-2 520 · say "REQ-4 not important" · confirm · done
uv run python -m scripts.review_requirements scripts/example_request.json --demo

uv run bmwow-validate ../contracts/ontology/examples/synthetic.json   # ontology validation
cd .. && pnpm install && pnpm preprocess --self-check                 # preprocessing logic, no network
```

### Full setup with data

Copy `.env.example` to `.env` at the repository root and fill in `DATABASE_URL` (Neon),
`OPENAI_API_KEY`, `LLM_STRONG` and `LLM_CHEAP`. Then:

```sh
pnpm preprocess                                 # feedback CSVs in data/feedbacks/ → Neon (~4 min, ~$1.35)
pnpm exec tsx scripts/import-sales.ts           # sales CSVs in data/sales/ → Neon

cd python
echo '{"model_code": "G60", "regions": ["EU"]}' > ../data/request.json
uv run python -m scripts.run_analysis ../data/request.json \
  --snapshot ../data/knowledge/snapshot.json \
  --knowledge-config ../data/knowledge/snapshot.config.json --env-file ../.env
uv run python -m scripts.export_analysis ../data/processed/analyses/<run_id>.json --write

cd .. && pnpm dev                               # http://localhost:3000
```

The request names the car (G60, F70 or G68) and, optionally, the regions. With no regions, the run covers all of the car's
regions. To run the PM gate on real data, use `review_requirements` with the same flags instead of
`run_analysis`. The knowledge snapshot is built from private workbooks; see
[knowledge ingestion](docs/knowledge-ingestion.md).

### Web research backends

`SEARCH_BACKEND` picks where the competition and trends agents read the web:

- `firecrawl` (default): live search and page scraping with an on-disk cache.
  `OFFLINE_MODE=true` replays the cache.
- `corpus`: a reviewed list of public URLs (`python/bmwow/agent/web_corpus_sources.yaml`),
  downloaded once with plain GET requests by `scripts/build_web_corpus.py` and then searched
  locally with BM25. It follows no links and fetches nothing at runtime. We use it for demos
  because results are reproducible.

Other providers (`openai`, `brave`) can plug in behind the same interface. They are declared but not
implemented yet.

## Limitations and next steps

- The PM gate runs in the terminal. In the web app, the chat is read-only. Moving the gate actions
  into the dashboard, and exporting the approved requirements as a report, are the next steps.
- The demo web corpus is a fixed, reviewed page set, not a crawler. Live search runs through
  Firecrawl.
- Region and market lists (`python/bmwow/agent/regions.yaml`, `models.yaml`) are placeholders, to
  be confirmed with the data.
- The Python pipeline is not yet ported to TypeScript. Neo4j persistence and full catalog extraction
  are follow-up work.

## Development

Checks: `pnpm lint`, `pnpm fmt:check`, `pnpm test` and `pnpm build` at the root, plus `uv run pytest`,
`uv run ruff check .`, `uv run ruff format --check .` and `uv run bmwow-schema --check` in
`python/`. Contributors work in git worktrees and follow the porting rule; see
[AGENTS.md](AGENTS.md).

### Chat configuration

`/api/chat` (`src/server/chat/agent.ts`) uses `OPENAI_API_KEY` and `LLM_STRONG`. Queries are
embedded with `text-embedding-3-large` at 1536 dimensions to match the stored vectors. The client
sends only the page scope from the URL (car, region, engine, feature), and the server validates it.
Threads live in the browser only. Web search uses `LLM_CHEAP` (falling back to `LLM_STRONG`),
localised to the page's country.

### Sales CSV import

Place the private CSV exports in `data/sales/`, with filenames ending in ` - <model code>.csv`.
`pnpm exec tsx scripts/import-sales.ts --self-check` runs on synthetic data without a network. The
importer validates every file before writing, applies `migrations/0001_sales.sql`, and upserts in
one transaction. It uses `DATABASE_URL_UNPOOLED`, or falls back to `DATABASE_URL` without the pooler
suffix. `G60_G68` is temporarily stored as `G60`, and its volumes represent the combined source
group.

## Docs

- [Project plan](docs/project-plan.md): milestone, team boundaries, Neon, and the BMW data boundary.
- [Ontology](docs/ontology.md): object meanings, validation, agent tools.
- [Definitions](docs/definitions.md): shared types and ontology vs analysis records.
- [Ontology consumers](docs/ontology-consumers.md): a worked requirement dossier.
- [Knowledge layer](docs/data-layer.md) and [knowledge ingestion](docs/knowledge-ingestion.md).
- [Feedback preprocessing](docs/preprocess-pipeline-spec.md), with terms in [CONTEXT.md](CONTEXT.md).
- [Web research](docs/web-research.md): the evidence collection contract.
- [Pipeline (orchestration v1)](python/bmwow/agent/README.md): module map and design decisions
  ([original spec](python/bmwow/agent/SPEC.md)).
- [Agent coordination](docs/agent-coordination.md): issue #3, human approval and privacy.

## Data and sharing

**BMW prohibits uploading its data to GitHub, including to private repositories.** Share code,
schemas, migrations and synthetic fixtures through GitHub. Keep originals and anything derived from
them local or in BMW-permitted storage, including exports, embeddings, generated analyses,
screenshots, logs and transcripts. Neon is the access-controlled database: commit its migrations and
import scripts, never its contents or credentials. See the
[data boundary](docs/project-plan.md#bmw-data-boundary).

Entire hooks are enabled and can upload transcripts in separate Git refs on push. Run
`entire configure --local --skip-push-sessions` in every clone and worktree before pushing. See
[keeping checkpoints local](https://docs.entire.io/guides/checkpoints/keep-checkpoints-local).
