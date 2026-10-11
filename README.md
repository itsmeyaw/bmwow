# BMWow: a BMW product decision assistant

This is an EHL Munich hackathon project for the BMW challenge. It turns customer
feedback, studies, sales data, public sentiment, competitor information, and
trends into traceable requirements for successor vehicles. Human review stays
separate from agent proposals.

## Architecture

- **App (TypeScript):** a single Next.js app serves as both frontend and backend,
  managed with pnpm. UI is in `src/app/` and `src/components/`. Route handlers go
  in `src/app/api/`, and server-only logic goes in `src/server/`.
- **Reference implementation (Python):** the backend logic lives in
  [`python/`](python/README.md) as a self-contained uv project, because some
  teammates work only in Python. Each module is later ported to `src/server/`
  under the same module name. See the porting rule in [AGENTS.md](AGENTS.md).
- **Contracts:** the JSON files in `contracts/ontology/` are what both languages
  share. They are generated from the Python ontology models.

```text
src/app/              Next.js pages and route handlers (api/)
src/components/ui/    shadcn/ui components (base-vega, hugeicons)
src/lib/              Client-safe helpers (cn)
src/server/           Server-only backend logic; ported Python modules land here
  db/schema.ts        Drizzle mirror of migrations/ (Neon Postgres + pgvector)
  analysis/queries.ts Ranking, evidence, and sales reads behind the analysis pages
  chat/               Analysis chat agent (/api/chat): page context, tools, hybrid search
scripts/preprocess.ts Feedback CSV -> OpenAI enrichment -> Neon (docs/preprocess-pipeline-spec.md)
migrations/           SQL DDL, the source of truth for the Neon schema
contracts/ontology/   Generated schema/vocabulary/agent contracts, plus hand-kept mappings and fixture
python/               Python reference implementation: bmwow.{ontology,knowledge,agent}, tests, scripts
docs/                 Guides (listed below)
data/, raw_data/      Local BMW inputs and caches; gitignored and never committed
```

## Setup

You need Node with the pnpm version from `package.json`, plus Python 3.12 with
[uv](https://docs.astral.sh/uv/) for `python/`. Copy `.env.example` to `.env` at
the repository root.

```sh
pnpm install
pnpm dev                      # http://localhost:3000
pnpm preprocess --self-check  # pipeline logic only, no network

cd python && uv sync --locked && uv run pytest
```

The checks are `pnpm lint`, `pnpm fmt:check`, `pnpm test`, and `pnpm build`, plus the Python
checks listed in [`python/README.md`](python/README.md). Agents and contributors
work in git worktrees; see [AGENTS.md](AGENTS.md).

### Analysis chat

The chat panel on the analysis pages posts to `/api/chat`
(`src/server/chat/agent.ts`). The client sends only the page scope from the URL:
car, `region`, and `engine`. The server validates it and puts that page's ranking,
summary, and sales into the prompt. With no car open, it uses the all-car ranking
and each car's top priority. The agent grounds its answers with tools. Hybrid
search (pgvector cosine plus `search_tsv`, fused with RRF) finds verbatims, and
the analysis queries cover other scopes. Answers cite feedback IDs such as
`[G70-0042]`, which render as chips that show the verbatim.

It uses `OPENAI_API_KEY` and `LLM_STRONG` (falling back to the preprocessing
model). Queries are embedded with `text-embedding-3-large` at 1536 dimensions to
match the stored vectors. Threads live in the browser only. The chat sends
verbatims and aggregates to OpenAI, the same provider `pnpm preprocess` uses.

### Sales CSV import

Place the private CSV exports in `data/sales/`, with filenames ending in
` - <model code>.csv`, then run from the repository root:

```sh
pnpm exec tsx scripts/import-sales.ts --self-check  # synthetic, no network
pnpm exec tsx scripts/import-sales.ts             # .env database connection
```

The importer validates all files before writing, applies `migrations/0001_sales.sql`,
and upserts `sales` in one transaction, verifying every stored value. Reruns update
matching `(model_code, market_code)` pairs without duplicating them. It uses
`DATABASE_URL_UNPOOLED`, falling back to `DATABASE_URL` with Neon's pooler suffix
removed for a direct connection. Existing environment variables take precedence over `.env`.

Only `market_code` is stored; the `market` label is ignored. The three volume columns
retain their source years and explicit zeros. At the user's request, `G60_G68` is
temporarily stored as `G60`; its volumes still represent the combined source group,
not an independently measured G60 total. `source_file` and `source_row` preserve the
original filename and CSV line number (header is line 1). This raw import does not
change the ontology's combined-model mapping or classify future volumes as historical.

To inspect SQL feedback across EU member countries, add `--region EU` to the
inspection command in the [Python setup guide](python/README.md). Direct country
filters remain available, and each feedback keeps its original country.

The Python knowledge layer also combines private JSON ontology snapshots with
read-only Neon feedback. Sales/study workbook import, reviewed mapping configuration,
and local candidate acceptance are implemented; see [knowledge ingestion](docs/knowledge-ingestion.md)
for setup. Segment/Feature curation, full catalog extraction, requirement/review
integration, TypeScript porting, and Neo4j persistence remain follow-up work.

## Docs

- [Project plan](docs/project-plan.md): the milestone, team boundaries, Neon, and the BMW data boundary.
- [Ontology](docs/ontology.md): object meanings, validation, agent tools, and v0.1 migration.
- [Definition boundaries](docs/definitions.md): shared types, ownership, and distinctions between ontology objects and analysis/read records.
- [Ontology consumers](docs/ontology-consumers.md): a worked requirement dossier with frontend and orchestration recipes.
- [Knowledge layer](docs/data-layer.md): snapshot, Neon, and combined reads; identity, source scope, citations, and the v1 handoff.
- [Knowledge ingestion](docs/knowledge-ingestion.md): combined reads, private sales/study imports, reviewed mappings, and validated candidate writes.
- [Feedback preprocessing](docs/preprocess-pipeline-spec.md): the TypeScript CSV-to-Neon pipeline. Its terms are in [CONTEXT.md](CONTEXT.md).
- [Web research](docs/web-research.md): the proposed evidence collection contract.
- [Agent coordination](docs/agent-coordination.md): issue #3, human approval, and privacy.
- [Orchestration v1](python/bmwow/agent/README.md): the agent module map ([original spec](python/bmwow/agent/SPEC.md)).

## Data and sharing

**BMW prohibits uploading its data to GitHub, including to private repositories.**
Share code, schemas, migrations, and synthetic fixtures through GitHub. Keep
originals and anything derived from them local or in BMW-permitted storage. That
includes exports, embeddings, generated proposals, screenshots, logs, and
transcripts. Neon is the selected access-controlled database; commit its
migrations and import scripts, but never its contents or credentials. CI uses
synthetic data only. See the [data boundary](docs/project-plan.md#bmw-data-boundary).

### Entire checkpoint sharing

Entire hooks are enabled. On push, they can upload captured prompts,
transcripts, and tool results in separate Git refs, even though
`.entire/metadata/` is ignored. To keep checkpoints local, run this in **every
clone and every worktree** before you push:

```sh
entire configure --local --skip-push-sessions
```

The command writes `push_sessions: false` to the ignored
`.entire/settings.local.json`. Do not push `entire/*` branches or use
`--all`/`--mirror`. The setting does not remove checkpoints that were already
pushed. See
[keeping checkpoints local](https://docs.entire.io/guides/checkpoints/keep-checkpoints-local).
