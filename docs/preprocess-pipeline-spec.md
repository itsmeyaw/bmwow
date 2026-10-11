# Spec: BMW Customer Feedback Preprocessing Pipeline

> Status: ready-for-agent. Derived from a 4-round design interview; every decision below was
> explicitly confirmed. Facts marked **(verified)** were measured against the real data,
> the installed SDKs, or the live Neon branch — not assumed.

## Problem Statement

We have three CSV exports of BMW customer feedback (F70 / G60 / G70) sitting inert in
`data/feedbacks/`. Nobody can answer "what are 7 Series owners complaining about in the
infotainment system?" without opening a spreadsheet, and nothing can power an LLM/RAG
workflow over the verbatims.

The raw exports are hostile to direct querying:

- **(verified)** 13,771 rows but only **10,128 unique feedbacks** — the files are already
  aspect-exploded, one row per (feedback, aspect). A naive load double-counts every
  multi-aspect feedback.
- **(verified)** The aspect taxonomy is already present but far too granular for a UI:
  **227 distinct `Vfc level2 Name` values** and **85 distinct `Vfc level3 Name` values**.
  A filter dropdown with 227 options is unusable.
- **(verified)** Dirty values: `BEVE` appears 3,110 times where `BEV` is meant; one
  `Engine Type` is pure whitespace; `Brand` and `Sales Description` are bracketed
  (`[BMW]`, `[BMW 5 Series]`); one category contains a non-breaking space
  (`ground\xa0clearance`).
- **(verified)** 2,082 `no_class_found` + 400 blank rows mean **1,180 feedbacks (11.6%)
  carry no usable aspect label at all**, despite having full verbatim text.
- **(verified)** There is **no date column anywhere** in the source data.
- There are no embeddings, so no semantic search is possible.

## Solution

A standalone TypeScript script, run on demand, that ingests the CSVs, normalizes and
cleans them, enriches them via OpenAI, and publishes a two-table relational model into
Neon Postgres with `pgvector`. A downstream Next.js app can then serve dashboard
aggregates with plain `GROUP BY` queries and hybrid (vector + lexical) semantic search
for RAG.

The pipeline is **idempotent and resumable**: re-running it after a crash or a
rate-limit storm picks up exactly where it left off without duplicating rows or
re-spending on work already done.

A full run costs **~$1.35** and takes **~4 minutes**.

## User Stories

### Dashboard consumer

1. As a product owner, I want to see the count of feedbacks per model (`derivate_code`), so that I can tell which vehicle line generates the most customer commentary.
2. As a product owner, I want to filter feedback by engine type (`BEV` / `PHEV` / `ICE`), so that I can isolate electrification-specific pain points.
3. As a product owner, I want to filter by both model and engine type simultaneously, so that I can look at e.g. only the BEV 7 Series.
4. As a product owner, I want to see feedback volume broken down by country, so that I can tell whether a complaint is regional or global.
5. As a product owner, I want to see counts grouped into roughly 16 coarse categories rather than 227 raw labels, so that the category filter is actually usable in a dropdown.
6. As a product owner, I want to drill from a coarse category into the specific raw aspect terms underneath it, so that "Infotainment & Connectivity" can be decomposed into "Touch screen, operation" vs "Apple CarPlay".
7. As a product owner, I want to see the positive/negative/neutral split within any category, so that I can tell praise from complaint at a glance.
8. As a product owner, I want to rank categories by average sentiment score, so that I can identify the worst-performing areas of the vehicle.
9. As a product owner, I want to see an issue-type breakdown (Malfunction vs Usability Difficulty vs Feature Request vs Praise), so that I can route findings to the right internal team — a malfunction goes to engineering, a usability difficulty goes to UX.
10. As a product owner, I want to filter by the original `Feedback Type` (`Likes` / `Difficult to Use` / `Wants` / `Defect`), so that I can reconcile the dashboard against the source system's own classification.
11. As a product owner, I want to slice by `source` (A/B/C/D), so that I can distinguish owner-written reviews from dealer-call transcripts, which have very different tone and reliability.
12. As a product owner, I want to know which aspects were machine-inferred rather than human-labelled, so that I can exclude inferred data from a report going to a sceptical stakeholder.
13. As a product owner, I want feedbacks with multiple aspects counted once in the feedback total but once per aspect in the aspect breakdown, so that neither number is inflated.
14. As a product owner, I want to rank individual feedbacks by sentiment intensity within an issue type, so that I can surface the five angriest malfunction reports rather than an arbitrary five.

### Search / RAG consumer

15. As an analyst, I want to search feedback by meaning rather than keyword, so that "the screen is slow" finds "touchscreen takes ages to respond".
16. As an analyst, I want exact-token search to still work, so that searching `iDrive 8.5` or `Bowers & Wilkins` finds those literal mentions that embeddings tend to blur.
17. As an analyst, I want semantic and lexical results fused into one ranked list, so that I get both behaviours from a single search box.
18. As an analyst, I want semantic search to cover feedbacks that have no aspect label, so that the 11.6% unclassified tail is still discoverable.
19. As an LLM/RAG workflow, I want to retrieve the top-k most semantically similar verbatims for a question, so that I can ground an answer in real customer language.
20. As an LLM/RAG workflow, I want retrieved verbatims to arrive with their structured aspects and sentiment attached, so that I can cite "3 of 5 retrieved feedbacks were Malfunction reports".
21. As an analyst, I want to combine a semantic search with structured filters, so that I can ask "feedback semantically about charging speed, but only for BEV G70 in the US".

### Pipeline operator

22. As an operator, I want to run the whole pipeline with a single command, so that there is no multi-step runbook to get wrong.
23. As an operator, I want to cap the run to the first N feedbacks, so that I can validate output for fractions of a cent before committing to the full spend.
24. As an operator, I want re-running the pipeline to skip feedbacks already fully processed, so that a crash at 90% doesn't cost me a full re-run.
25. As an operator, I want a feedback that fails enrichment to leave _no_ partial row behind, so that the resume marker never lies to me about what's done.
26. As an operator, I want failed feedback IDs reported at the end of the run, so that I know what to investigate rather than discovering gaps in the dashboard.
27. As an operator, I want the run to survive OpenAI rate limiting without manual intervention, so that I don't babysit it.
28. As an operator, I want a printed summary of rows read, feedbacks written, aspects written, failures, and estimated cost, so that I can sanity-check the run in one glance.
29. As an operator, I want the category/issue-type mapping committed to the repo as a reviewable file, so that bucketing is stable across runs and my dashboard numbers don't silently drift.
30. As an operator, I want to hand-correct a bad bucket assignment by editing that file, so that fixing a mis-categorization costs zero API spend.
31. As an operator, I want the pipeline to only call the LLM for taxonomy labels missing from that file, so that adding a fourth CSV doesn't re-classify the existing 312 labels.
32. As an operator, I want a fast self-check I can run without any API keys or database, so that I can verify the cleaning and mapping logic in isolation.
33. As an operator, I want the pipeline to fail loudly and immediately if `OPENAI_API_KEY` or `DATABASE_URL` is missing, so that I don't discover a misconfiguration on call 9,000.

### Data quality consumer

34. As a data consumer, I want `BEVE` normalized to `BEV`, so that engine-type aggregates aren't split across a typo.
35. As a data consumer, I want bracket characters stripped from brand and model names, so that the UI renders "BMW 5 Series" and not "[BMW 5 Series]".
36. As a data consumer, I want all string fields trimmed, so that " US" and "US" aren't two countries.
37. As a data consumer, I want whitespace-only values stored as NULL, so that "empty" is representable exactly one way.
38. As a data consumer, I want empty, sub-5-character, and placeholder (`N/A`, `None`) verbatims rejected, so that garbage never reaches an embedding call.
39. As a data consumer, I want the original raw VFC label preserved alongside its coarse bucket, so that a bucketing mistake is recoverable with an UPDATE rather than a full re-ingest.
40. As a data consumer, I want each aspect to record whether it came from the curated VFC label or from LLM inference, so that provenance is always auditable.
41. As a data consumer, I want `sentiment` derived from the curated taxonomy rather than from model intuition, so that dashboard counts are stable across re-runs.
42. As a data consumer, I want a feedback's multiple conflicting `Feedback Type` values all preserved, so that a feedback praising the engine _and_ reporting a defect is counted in both.

## Implementation Decisions

### Module layout

Four artifacts:

1. **Drizzle schema module** — the single source of truth for table and column names.
   Consumed by both the pipeline and the downstream Next.js app so they cannot drift.
2. **SQL migration** — hand-written DDL, applied once. Creates the `vector` extension,
   both tables, and all indexes.
3. **Pipeline script** — the executable. Orchestrates read → clean → taxonomy → enrich →
   embed → write.
4. **Committed taxonomy mapping file** (JSON) — the 312-entry label→bucket map, generated
   once by the LLM and thereafter owned by humans.

**Decision: `drizzle-kit generate` is not wired up.** Running a release-candidate
migration generator for one table pair is more ceremony than value. The Drizzle schema
module exists purely so the app gets typed queries; DDL is applied from the hand-written
SQL file.

### Database driver

`pg` (node-postgres) over a pooled TCP connection, via `drizzle-orm/node-postgres`.

The repo previously contained only `@libsql/client` (SQLite) — wrong database entirely.
Neon's HTTP driver was rejected: bulk-inserting ~24k rows and ~10k vectors over
one-shot HTTP requests is materially slower than a pooled TCP connection, and this is a
batch script, not an edge function.

### Schema: `feedback_entries` (parent, one row per unique feedback)

| column                 | type                        | notes                                  |
| ---------------------- | --------------------------- | -------------------------------------- |
| `id`                   | `UUID` PK                   | `gen_random_uuid()`                    |
| `feedback_explorer_id` | `TEXT` **UNIQUE NOT NULL**  | from the CSV's `ID` column             |
| `source`               | `TEXT`                      | **added** — see below                  |
| `brand`                | `TEXT`                      | brackets stripped                      |
| `sales_description`    | `TEXT`                      | brackets stripped                      |
| `country`              | `TEXT`                      |                                        |
| `derivate_code`        | `TEXT`                      |                                        |
| `engine_type`          | `TEXT`                      | `BEVE`→`BEV` normalized                |
| `raw_feedback`         | `TEXT NOT NULL`             | original verbatim                      |
| `embedding`            | `vector(1536)`              |                                        |
| `search_tsv`           | `tsvector` GENERATED STORED | `to_tsvector('english', raw_feedback)` |
| `created_at`           | `TIMESTAMPTZ`               | `NOW()`                                |

Deviations from the original brief, each deliberate:

- **`translated_feedback` dropped entirely, along with the translation API call.**
  **(verified)** Every sampled verbatim is already English, including the JP/KR/SE/FR
  rows — the upstream system appears pre-translated. 135 rows contain non-ASCII
  characters but these are typographic artifacts (`▶`), not foreign script. A blanket
  per-row translate call would have doubled LLM cost and latency for approximately zero
  rows. Embeddings are generated from `raw_feedback` directly.
- **`feedback_type` moved to the child table.** **(verified)** 1,495 IDs (14.8%) carry a
  _different_ `Feedback Type` on each of their rows — e.g. `F70-0002` is `Likes` for
  Workmanship _and_ `Difficult to Use` for Owner's Manual, from one verbatim. The field
  is an attribute of the aspect, not the feedback. Leaving it on the parent would force
  the loader to discard one value, undercounting Defects whenever a feedback both praised
  and complained. Not duplicated onto the parent.
- **`source` added.** **(verified)** 4 values (A/B/C/D) present in the CSV with no home
  in the original schema. Almost certainly distinguishes dealer-call transcripts from
  owner-written reviews — a dimension worth slicing by. One column now beats a migration
  later.
- **`search_tsv` added.** The brief asked for _hybrid_ semantic search; a pure HNSW
  cosine search is only the semantic half. The lexical half catches model codes, trim
  names, and feature names verbatim — exactly what users type. One generated column,
  one GIN index, zero API spend.
- **`Vfc level2 3 Name` not stored.** **(verified)** It is `level2 : level3`
  concatenated — only 5 of 13,771 rows differ, and those merely omit the space before
  the colon. Fully derivable.

### Schema: `feedback_aspects` (child, 1:N)

| column              | type            | notes                                        |
| ------------------- | --------------- | -------------------------------------------- |
| `id`                | `UUID` PK       | `gen_random_uuid()`                          |
| `feedback_entry_id` | `UUID` FK       | → `feedback_entries.id` `ON DELETE CASCADE`  |
| `feedback_type`     | `TEXT`          | **relocated from parent**                    |
| `vfc_category`      | `TEXT NOT NULL` | coarse bucket, ~16 values                    |
| `aspect_term`       | `TEXT`          | raw `Vfc level2 Name`, 227 values            |
| `aspect_label_raw`  | `TEXT`          | **added** — raw `Vfc level3 Name`, 85 values |
| `issue_type`        | `TEXT NOT NULL` | **added** — coarse bucket, ~11 values        |
| `quote_snippet`     | `TEXT`          | populated for LLM-extracted aspects only     |
| `sentiment`         | `TEXT NOT NULL` | Positive / Negative / Neutral                |
| `sentiment_score`   | `NUMERIC(3,2)`  | −1.00 … +1.00, CHECK-constrained             |
| `extraction_source` | `TEXT NOT NULL` | **added** — `vfc_label` \| `llm`             |
| `created_at`        | `TIMESTAMPTZ`   | `NOW()`                                      |

`aspect_label_raw` and `extraction_source` exist so that bucketing errors are fixable
with an UPDATE and so provenance is always auditable. Two TEXT columns at 13,771 rows
costs nothing.

A `CHECK` constrains `sentiment_score` to [−1, 1]. The zod schema already bounds it, but
LLM output is an untrusted input crossing into the database — the constraint stays.

### Indexes

- `(derivate_code, engine_type)` on entries — as briefed.
- `(vfc_category, sentiment)` on aspects — as briefed.
- HNSW `vector_cosine_ops` on `feedback_entries.embedding` — as briefed.
- GIN on `search_tsv` — added for the lexical half of hybrid search.
- btree on `feedback_aspects.feedback_entry_id` — FK join support.

**Decision: no materialized views, no summary tables.** At ~10k parents and ~14k aspects
Postgres will scan the entire dataset in single-digit milliseconds; a live `GROUP BY` is
faster than maintaining a refresh. The two btree indexes will likely never be chosen by
the planner at this size — they are kept as free insurance against 100× growth.

### Cleaning rules

Header normalization to `snake_case`: `ID` → `feedback_explorer_id`,
`Derivate (e-code)` → `derivate_code`, `Sales Description` → `sales_description`, etc.

Value cleaning, in order: trim all strings → strip surrounding `[` `]` from `brand` and
`sales_description` → `BEVE` → `BEV` → whitespace-only → NULL → normalize non-breaking
spaces in taxonomy join keys (**(verified)** required: `ground\xa0clearance`).

Verbatim rejection: empty, `< 5` characters, or placeholder (`N/A`, `None`, `NA`,
`null`, `-`, `.`, case-insensitive). **(verified)** Zero rows in the current data trip
any of these — the filter is defensive, for future exports.

### Parent deduplication

Collapse the 13,771 rows onto `feedback_explorer_id` → 10,128 parents.

**(verified)** Safe: every repeated ID agrees on `Source`, `Country`, `Engine Type`,
`Sales Description`, and `Customer Feedback` — zero conflicts across the entire dataset.
No ID spans two derivates. Only `Feedback Type` and the VFC columns vary, and those now
live on the child.

### Enrichment: pass 1 — taxonomy classification

**The central decision: classify the vocabulary, not the rows.**

The 13,771 rows contain only **227 + 85 = 312 distinct label strings**, repeated
thousands of times. So instead of ~13,771 row-level LLM calls, the pipeline makes **312
classifications in ~11 batched requests** (~30 labels per request), writes the result to
a committed JSON file, and thereafter maps rows against that file with zero API calls.

This is 44× cheaper, but cost is the smaller win. The real wins:

- **Deterministic.** Row-level classification would bucket the same label differently on
  different days, and dashboard numbers would drift between runs for no reason.
- **Reviewable.** A 312-line JSON file is something a human can read and correct in five
  minutes. An LLM mis-bucketing `Drivetrain` row-by-row is invisible; mis-bucketing it
  once in a committed file is obvious in a diff.
- **Incremental.** Only labels _absent_ from the file trigger an API call, so a fourth
  CSV classifies only its new labels.

Closed vocabularies — the model must select from the list or return `Unclassified`, and
**must never invent a bucket** (enforced by Structured Outputs enums, not by validation
code). Free-text output here is how you end up with `Infotainment`, `infotainment`, and
`Infotainment & Connectivity` as three separate filter options.

`vfc_category` (16), derived by reading all 227 actual values:

> Infotainment & Connectivity · ADAS / Driving Assistance · Powertrain & Performance ·
> Chassis, Ride & Handling · Electrification & Charging · Climate Control ·
> Seats & Comfort · Interior Design & Materials · Exterior Design & Body ·
> Storage & Luggage · Access, Locking & Keys · Visibility & Lighting ·
> Instruments & Controls · Safety & Restraints · Service, Docs & Support · Unclassified

`issue_type` (11), derived by reading all 85 actual values:

> Praise · Usability Difficulty · Malfunction · Damage & Leaks ·
> Performance Shortfall · Feature Request · Noise, Vibration & Odor ·
> Space & Storage Shortfall · Value & Pricing · Information Quality · Unclassified

Model: `gpt-6-luna` with **`reasoning.effort: "high"`**. Bucketing 227 ambiguous BMW
taxonomy strings is the one genuinely hard judgement in the pipeline and it happens 11
times — cost is a rounding error, so pay for quality.

### Enrichment: pass 2 — per-feedback scoring and extraction

**One unified LLM call per unique feedback (10,128 calls).** The call receives the
verbatim plus its already-mapped aspects and returns a sentiment intensity per aspect.
For the **(verified)** 1,180 feedbacks with no usable label, the same call shape extracts
aspects from scratch — constrained to the same closed vocabularies — and populates
`quote_snippet`.

Rejected alternative: one call per aspect (13,771). It re-sends each verbatim 13,771
times instead of 10,128, is 36% more requests, and scores each aspect blind to its
siblings — so "the engine is brilliant but the screen lags" yields two independently
scored aspects with no awareness that they are a contrast.

Output contract (Structured Outputs, strict, via zod):

```ts
{
  // one intensity per aspect sent, in the order sent; length MUST match
  scores: number[],            // 0..1 magnitude only — sign comes from issue_type
  // populated only when zero aspects were sent (the unlabeled 1,180)
  extracted: Array<{
    vfc_category: VfcCategory, // enum, 16 literals
    issue_type: IssueType,     // enum, 11 literals
    aspect_term: string,
    quote_snippet: string,
    intensity: number,         // 0..1
  }>
}
```

`reasoning.effort: "low"`. Scoring intensity on a verbatim whose aspect is already
identified is a classification task; `medium` (the default) would roughly double output
tokens for no measurable gain. `none` was rejected because the same call also performs
extraction for the unlabeled tail, which does need some reasoning.

A `scores` array whose length doesn't match the aspects sent is treated as a failure and
enters the retry path.

### Sentiment derivation

**`issue_type` is authoritative for `sentiment`; the LLM score is intensity only.**

- `Praise` → `Positive`
- `Feature Request` → `Neutral`, score forced to `0.00`
- `Unclassified` → `Neutral`, score forced to `0.00`
- everything else → `Negative`

`sentiment_score` = the bucket's sign × the LLM's intensity magnitude. So the model can
say a malfunction was mentioned mildly (−0.15) or furiously (−0.95), but it can never
flip a curated `Malfunction` into a positive.

Rationale: the curated VFC label came from a human taxonomy, not an inference — it is the
stronger signal. It also keeps `COUNT(*) WHERE sentiment='Negative'` stable across
re-runs, which a score-threshold-derived sentiment would not be. The score then does what
a score should: rank _within_ a sentiment class.

`Feature Request` is deliberately Neutral rather than Negative — counting 754 "I wish it
also did X" rows as complaints would inflate detractor numbers.

### Enrichment: pass 3 — embeddings

**`text-embedding-3-large` with `dimensions: 1536`.**

Facts behind this, all **(verified)**:

- OpenAI's embedding lineup has not changed since January 2024. The installed SDK exposes
  exactly three models: `ada-002` (legacy), `3-small` (1536, $0.02/M, MTEB 62.3),
  `3-large` (3072 default, $0.13/M, MTEB 64.6). **There is no `text-embedding-4`.**
- **pgvector caps HNSW indexes at 2,000 dimensions for the `vector` type.** The brief
  requires an HNSW index, so full 3072-dim `3-large` is structurally impossible without
  switching the column to `halfvec(3072)` (HNSW cap 4,000).
- `3-large` is Matryoshka-trained. Requesting `dimensions: 1536` returns a truncated
  vector — confirmed against the live API, returns exactly 1536 — that **still
  outperforms `3-small` at the same 1536 dims**, in the same `vector(1536)` column the
  brief already specified, with identical storage and identical HNSW behaviour.
- Cost difference over the whole corpus (554k tokens): **$0.072 vs $0.011 — six cents.**

The genuine 2026 MTEB leaders are not OpenAI (Cohere `embed-v4` 65.2, Gemini Embedding 2
~68.3 multilingual, `voyage-4`, self-hosted `Qwen3-Embedding-8B` 70.6) but each means a
second vendor, a second key, and a second failure mode — rejected for a six-cent corpus.

Embedding grain is **parent only**, one vector per feedback. **(verified)** verbatims are
p50 190 / p90 734 / p99 1,753 / max 4,260 characters — all comfortably inside the
8,191-token limit, so no chunking. Aspect-level vectors were rejected: they would mean
13,771 near-duplicate embeddings of overlapping text.

Batching: up to 2,048 inputs / 300k tokens per request → the whole corpus is **~21
requests**.

### Atomicity and resume

**One transaction per feedback. Enrich first, then write parent + all its aspects +
embedding atomically, or write nothing.**

This corrects an earlier design. The obvious resume marker — "skip feedbacks that
already have an embedding" — is unsound under a two-phase write: if the parent lands with
its embedding and enrichment then fails, the next run sees an embedding, skips the
feedback, and **its aspects never arrive, silently**. The marker would be lying.

With a single transaction, "has embedding" becomes truthful, so the resume predicate stays
a one-column check and the pipeline is self-healing on re-run. Because embeddings are
batched across feedbacks for efficiency, the script processes in chunks: embed the chunk
in one request → enrich the chunk concurrently → commit one transaction per feedback.

On permanent failure: log the ID to stderr, increment a counter, continue. The next run
picks it up. No dead-letter file to reconcile, no `status` column.

### Concurrency and rate limits

**(verified)** against the live API with the configured key:

- `gpt-6-luna`: 5,000 RPM / **2,000,000 TPM**. The enrichment pass is ~6.4M tokens, so
  **TPM is the binding constraint**, giving a ~3.5 minute floor — RPM is irrelevant here.
- `text-embedding-3-large`: 5,000 RPM, no TPM cap advertised.

Policy: **`maxRetries: 5` on the OpenAI client plus a fixed semaphore of 25 in-flight
requests.** The SDK already performs exponential backoff with jitter on 429/5xx and
honours `retry-after`. A hand-rolled token-bucket limiter is ceremony — the server
already says when to slow down.

### Service tier

**Standard.** Batch and Flex are both 50% off, which on a $1.25 pass saves **62 cents** —
not worth a JSONL upload / polling / result-parsing state machine or an unpredictable
24-hour wall clock. Flex remains a one-word change if the discount is ever wanted.

### CLI surface

- `--limit N` — process only the first N feedbacks. The first real run should be
  `--limit 20` (~$0.003) to eyeball output before committing to the full spend. Omitting
  a brake on a 10,128-call script is how you pay twice.
- `--self-check` — run the in-process assertions; no API key, no database.

Both `OPENAI_API_KEY` and `DATABASE_URL` are validated at startup and the script exits
immediately if either is absent.

### Cost and runtime budget

| pass                    | calls  | cost               |
| ----------------------- | ------ | ------------------ |
| taxonomy classification | ~11    | ~$0.01             |
| per-feedback enrichment | 10,128 | ~$1.25             |
| embeddings              | ~21    | ~$0.07             |
| **total**               |        | **~$1.35, ~4 min** |

## Testing Decisions

### What makes a good test here

Only external behaviour. For this pipeline that means: _given these CSV rows, this
taxonomy map, and these enrichment results, produce exactly these database rows._ Tests
must not assert on helper function names, intermediate shapes, call ordering, or how many
times a private function ran. A test that breaks when the cleaning logic is refactored
but the output is unchanged is a bad test.

Tests must not hit OpenAI or Postgres. Both are someone else's correctness problem and
both make the suite slow, flaky, and expensive.

### The seam

**One seam.** A single pure function:

```
transform(csvRows, taxonomy, enrichments) → { entries, aspects }
```

Everything deterministic and worth testing lives behind it:

- header normalization and `snake_case` mapping
- string trimming, bracket stripping, `BEVE`→`BEV`, whitespace→NULL
- verbatim rejection (empty / `<5` chars / placeholders)
- non-breaking-space normalization on taxonomy join keys
- parent deduplication onto `feedback_explorer_id`
- `aspect_term` / `aspect_label_raw` / `vfc_category` / `issue_type` assignment
- `issue_type` → `sentiment` derivation, including the `Feature Request` → Neutral/0.00
  and `Unclassified` → Neutral/0.00 special cases
- sign application: `sentiment_score` = bucket sign × LLM intensity
- `extraction_source` tagging (`vfc_label` vs `llm`)

Everything non-deterministic stays outside it: the OpenAI client, the `pg` pool, the
transaction loop, the semaphore, the filesystem. Those are thin orchestration over an
already-tested core, and they are exercised by the `--limit 20` smoke run rather than by
unit tests.

This seam was chosen because it is the highest point at which the output is fully
determined by the input. Testing lower — at a `cleanRow()` or `mapLabel()` granularity —
would multiply seams and couple tests to internal structure for no additional coverage.

### Form of the check

**(Deliberately minimal.)** A `--self-check` flag on the script running `node:assert`
against the single seam. No test framework, no fixtures directory, no per-function
suites. Table-driven cases covering:

1. Three rows sharing one `ID` collapse to one entry and three aspects.
2. `BEVE` becomes `BEV`; `[BMW 5 Series]` becomes `BMW 5 Series`; whitespace-only becomes
   NULL.
3. A `no_class_found` row with LLM-extracted aspects gets `extraction_source: 'llm'` and
   a populated `quote_snippet`; a labelled row gets `'vfc_label'` and a NULL snippet.
4. A `Malfunction` aspect with intensity 0.9 yields `sentiment: 'Negative'`,
   `sentiment_score: -0.90`.
5. A `Feature Request` aspect yields `Neutral` / `0.00` regardless of reported intensity.
6. One `ID` with two different `Feedback Type` values produces two aspects, each keeping
   its own — the regression guard for the parent/child relocation decision.
7. A sub-5-character verbatim is rejected entirely, producing no entry and no aspects.

### Prior art

None — this repo has no test suite and no test tooling installed. The `--self-check`
approach is chosen specifically to avoid introducing a framework for seven assertions.
If a framework arrives later, these cases port directly, since they already address the
seam rather than the internals.

## Out of Scope

- **The Next.js dashboard and search UI.** This spec delivers the schema and indexes they
  need, nothing more. RRF fusion of vector + lexical results is ~15 lines in the app.
- **Translation.** Column and API call both removed. If a genuinely non-English export
  appears, the reinstatement is an ASCII-ratio + CJK-range heuristic that only calls the
  API when it trips — never a blanket per-row translate.
- **Time-series analysis.** **(verified)** The source data has no date column of any
  kind. `created_at` records when the script ran and is identical for every row, so
  "feedback over time" charts are impossible. Dates must be solved upstream at the data
  source; the pipeline must **not** synthesize or jitter a fake date.
- **Aspect-level embeddings.** Parent-only. Revisit only if RAG recall measurably
  disappoints.
- **`halfvec(3072)` full-fidelity embeddings.** The documented upgrade path if retrieval
  disappoints (a $0.07 re-embed plus a column migration) — not paid for before failure is
  observed.
- **Batch / Flex API tiers.** 62 cents of savings, rejected.
- **Per-aspect continuous scoring via a second model pass**, materialized views, summary
  tables, `drizzle-kit` migration generation, incremental/streaming ingest, and a
  `--force` full-rebuild flag. All deferred until something actually demands them.
- **Multi-vendor embeddings** (Cohere, Gemini, Voyage, self-hosted Qwen3).

## Further Notes

- **(verified)** Neon project `bmwow` exists: PG 18, `aws-us-east-2`, free tier, zero
  tables. `pgvector` **0.8.6** is available but not yet installed — the migration creates
  the extension.
- **(verified)** `.env` has both `OPENAI_API_KEY` and `DATABASE_URL` populated. Minor
  gotcha: the file cannot be `source`d in a shell because `DATABASE_URL` contains an
  unquoted `&`. Irrelevant to `dotenv` in Node; just don't `. ./.env`.
- **(verified)** `gpt-6-luna` is real and present in the installed `openai@7.31.0` SDK:
  $0.10/$0.50 per 1M tokens, 1.1M context, `reasoning.effort` ∈
  {`none`,`low`,`medium`,`high`,`xhigh`,`max`}, Structured Outputs on the Responses API.
- **(verified)** Drizzle `1.0.0-rc.4` provides `vector({ dimensions })` and
  `generatedAlwaysAs` in `pg-core` — both required features are present on the RC.
- Dependencies added: `pg`, `csv-parse` (no CSV parser was installed, and **(verified)**
  the G60 file contains quoted fields with embedded newlines and commas — hand-rolling a
  quote-aware parser would be the wrong kind of lazy), `@types/pg` as a dev dependency.
- `data/feedbacks/*.csv` stays local: `data/`, `raw_data/`, and `.env*` are gitignored (BMW data must not reach GitHub).
- The taxonomy JSON is **committed**, deliberately. Regenerating it per run would discard
  the entire reason vocabulary-level classification was chosen over row-level: that the
  output is a small artifact a human owns.
- If the ~16 / ~11 bucket sets need renaming, do it before the first full run. Changing
  them later means re-running the (cheap) taxonomy pass _plus_ a backfill UPDATE.
