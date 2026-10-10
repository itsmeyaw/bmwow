# SPEC — `bmwow/agent/`: Situation Analysis Agents

> **v2 note.** The pipeline was extended after this spec: validate, structure_agent (evidence
> packages, rubric judgment, guard) and gap_fill follow the four agents; feedback counts aspects
> instead of clustering; competition is a fixed search-and-extract workflow; baseline has no LLM
> step. See [README.md](README.md#pipeline-v2). Where they differ, the README describes the code.

> **Status:** original build spec for orchestration v1 (Python reference implementation). The API
> layer will be Next.js route handlers in TypeScript (`src/app/api/`, logic in `src/server/`).
>
> The bridge and knowledge read models described below are now implemented.
> Snapshot, feedback-only Neon, and combined reads are available, together with
> private workbook import and local candidate acceptance. The original builder
> instructions and illustrative snippets preserve the initial design brief;
> use [the current agent guide](README.md), [data-layer handoff](../../../docs/data-layer.md),
> and [ingestion guide](../../../docs/knowledge-ingestion.md) for current setup,
> record contracts, source scopes, and remaining write/workflow integration.
> [Definition boundaries](../../../docs/definitions.md) names the current canonical
> Python definitions. Repeated schema and fallback-config copies have been replaced
> with references to their owners; remaining builder snippets are historical.

> **For Claude (the builder).** This spec covers **only `bmwow/agent/`**: the four situation-analysis agents
> (`baseline_agent`, `competition_agent`, `feedback_agent`, `trends_agent`), their tools, and the service
> functions an API layer calls. Everything else in the repo is built by teammates.
>
> - **Do not implement** `bmwow/agent/knowledge_bridge/`, `bmwow/agent/models/`, the API layer or the frontend. §4 lists the
>   functions and schemas `agent/` needs from them. Code against those contracts. Until they exist, use
>   the stubs in `tests/fakes/` (§9).
> - **The repo structure and the data sources are suggestions, not fixed.** The team is still cleaning
>   the data and defining file structures. Keep every data access behind the interfaces in §4, so a
>   changed source or schema means changing one adapter, never an agent.
> - **Preserve the implemented contracts** (schemas, node names, output envelope, service functions)
>   at the canonical definitions linked below. Remaining code snippets are illustrative.
>   Check the installed versions of LangGraph, LangChain,
>   langchain-openai and firecrawl-py and adapt call signatures if they differ.
> - Never invent data. Every claim an agent emits must cite stored evidence.

---

## 1. Context

**The hackathon challenge.** BMW product management turns ~1 billion findings into ~1,000 requirements
into one car. A **requirement is a customer-relevant attribute of a car** (e.g. real-world range, seat
ventilation, intuitive UX), later quantified with a target value (e.g. "range: 600 or 700 km?").

The process from the brief:

**Situation analysis** → Structure & context → Requirements definition → Specification & quantification
→ Prioritization → Documentation

**This spec is only the first step, situation analysis.** It has four parallel agents that each look at
the product from one angle:

| Agent | Question it answers | Suggested inputs (may change) |
|---|---|---|
| `baseline_agent` | Where does our own product stand today? | previous BMW model, BMW portfolio, sales volume |
| `competition_agent` | What do competitors offer, at what values? | competitor entities in the ontology + live web |
| `feedback_agent` | What do customers and the public say, and how often? | customer / public feedback ingested into the knowledge layer |
| `trends_agent` | Which product and global trends matter? | studies in the ontology + live web |

**Their output feeds a downstream `structure_agent`, which is out of scope here.** It classifies,
clusters, dedupes and contextualizes the findings, and later stages generate requirements and specs from
them. The downstream app must be able to **back every argument when asked**, so the main job of these
four agents is to produce **atomic, attributed, evidence-linked findings**, not prose.

**Input.** The PM gives a **reference model code** (`G60`, `F70` or `G68`) and optionally **regions**
(`EU`, `CN`, `US`; none = all regions the model has data for). The run
analyzes the situation for **the successor of that model in those regions**. The reference model is the
baseline. Everything else (segment, powertrain, competitor set) is resolved from the knowledge layer, not
typed by the PM (§3.1).

---

## 2. Folder layout (`bmwow/agent/`)

Adapted from the team's suggested layout; files marked *(new)* are additions this spec needs.

```
bmwow/agent/
├── __init__.py
├── service.py            (new) public entry points for the API layer (§7)
├── supervisor.py         builds the analysis graph: fan-out to 4 agents, fan-in collect (§5)
├── state.py              (new) AnalysisState + reducers (§5.2)
├── config.py             (new) env, model tiers, budgets (§8)
├── llm.py                (new) model factory: strong / cheap / embeddings
├── router.py             maps an agent's data needs to SQL, ontology or web tools (§6.0)
├── validation.py         (new) citation + quantity checks (§6.0)
├── nodes/                (new) one module per agent
│   ├── baseline.py
│   ├── competition.py
│   ├── feedback.py
│   └── trends.py
├── prompts/              (new) one .md prompt per LLM step, loaded at runtime
└── tools/
    ├── graph_rag.py      wraps bmwow/agent/knowledge_bridge/ontology.py contracts as LangChain tools
    ├── sql_rag.py        wraps bmwow/agent/knowledge_bridge/sql_client.py contracts as LangChain tools
    ├── web_search.py     (new) Firecrawl search + scrape behind SearchBackend, with cache (§6.5)
    └── feedback_stats.py (new) dedupe / embed / cluster feedback (deterministic, §6.3)
```

`supervisor.py` must also expose the compiled graph as a **subgraph**, so the downstream pipeline can
mount it as one node later.

---

## 3. Output contract (what `structure_agent` receives)

The current schemas are defined once in [models/evidence.py](models/evidence.py):
Source, Quantity, Finding, AgentReport and SituationAnalysis. They retain original
source qualifications through the shared knowledge records. See
[definition boundaries](../../../docs/definitions.md) for their relationship to
persisted ontology objects; no schema copies are maintained in this spec.

### 3.1 Input: `AnalysisRequest` → resolved `ProductBrief`

[AnalysisRequest and ProductBrief](models/evidence.py) define the request and
resolved brief. The PM supplies a model code and optional registry regions.
Resolution supplies the reference model, curated segment, competitors, feedback
query selectors, research locales, and warnings. Research locales are typed
SearchLocale records, not strings. The live registry determines supported models
and coverage; this spec does not fix a list of three models.

Resolution rules:

- **`model_code` not in the registry → fail fast** with a clear error that lists the valid codes. Don't
  guess a model.
- **Unknown region → fail fast** and list the valid codes.
- **Model–region combination not in the registry → fail fast**, e.g. a model with data only in `CN`
  requested for `EU`. The error says which regions that model supports.
- The API and UI should offer **dropdowns filled from the registry** (`service.list_models()`), not free
  text, so invalid input mostly can't be entered in the first place. The validation above still runs on
  the backend.
- **No regions given** → all regions the model supports in the registry (e.g. `G68` → `["CN"]`).
- **No competitors found** for the segment and regions: `competition_agent` falls back to web discovery
  (§6.2).
- The resolved brief is **returned to the UI immediately** (§7), so the PM sees and can correct what the
  run will use.

---

## 4. Required contracts from other modules

The agents need these functions. They are the **only** coupling to `knowledge/`. If teammates build
different signatures, write a thin adapter in `agent/tools/` and leave the agents unchanged.

### 4.1 `bmwow/agent/knowledge_bridge/ontology.py` (graph)

```python
def get_model(model_code: str) -> ModelNode | None              # incl. attributes; None if unknown
def list_portfolio(segment: str | None = None, regions: list[str] | None = None) -> list[ModelNode]
def list_competitor_models(segment: str, regions: list[str], names: list[str] | None = None) -> list[ModelNode]
def get_attribute_values(model_id: str, attributes: list[str] | None = None) -> list[AttributeValue]
def get_feedback_items(filters: FeedbackFilter) -> list[FeedbackItem]       # bounded / iterable OK
def search_documents(query: str, kinds: list[str] | None = None, regions: list[str] | None = None,
                     k: int = 10) -> list[DocChunk]           # studies, reports
```

Read records are defined in [knowledge/records.py](../../knowledge/records.py).
[models/knowledge.py](models/knowledge.py) re-exports those same classes for old
imports. AttributeValue, ModelNode, FeedbackItem, DocChunk and FeedbackFilter
retain the current optional provenance/scope fields; do not re-create the initial
minimal record sketches.

### 4.2 `bmwow/agent/knowledge_bridge/sql_client.py` (relational)

```python
def sales_volume(models: list[str], markets: list[str] | None = None,
                 period_from: str | None = None, period_to: str | None = None) -> list[SalesRow]
```

SalesRow is defined in [knowledge/records.py](../../knowledge/records.py),
including original model groups, measurements, source status and citations.

Every function result becomes a `Source` in the agent. Ontology results map to `kind="ontology"` with
`ref=node_id`; SQL results map to `kind="sql"` with `ref` = the query parameters and `excerpt` = the
rendered rows.

### 4.3 Attribute taxonomy

Agents map every finding to a taxonomy attribute. Load it from `bmwow/agent/knowledge_bridge/ontology.py` if the
ontology defines it; otherwise fall back to `bmwow/agent/taxonomy.yaml`, seeded from the brief.

The fallback is maintained once in [taxonomy.yaml](taxonomy.yaml). Its analysis
areas are not ontology Domain values or coarse VFC categories. Reviewed Feature
mappings establish identity; similar labels do not.

Findings that fit no attribute get `attribute="unmapped:<name>"` and are kept. Downstream decides what
to do with them.

### 4.4 Regions

Load the list from the knowledge layer if it defines one; otherwise fall back to `bmwow/agent/regions.yaml`.
Each registry region supplies feedback query selectors and a research locale.
The fallback values are maintained once in [regions.yaml](regions.yaml).
Source-reported sales/study populations retain their own scope, as described in
[definition boundaries](../../../docs/definitions.md).

### 4.5 Model registry (the only models the app supports)

The registry is loaded from the knowledge layer when it offers
`list_supported_models()`; otherwise it uses [models.yaml](models.yaml).

- Names, segments, and sale availability require curation rather than inference
  from general knowledge or feedback coverage.
- A model's `regions` is the list of regions with data for that model. Resolution
  validates the requested regions against that coverage.
- Adding a model means adding its reviewed identity and connected coverage, or
  updating the explicit fallback. No hard-coded schema list is maintained here.

---

## 5. Graph (`supervisor.py`, `state.py`)

### 5.1 Topology

```
                        ┌─> baseline_agent ────┐
                        ├─> competition_agent ─┤
START ─> resolve_request┼─> feedback_agent ────┼─> collect ─> END
                        └─> trends_agent ──────┘
```

- `resolve_request` (deterministic, no LLM) builds the `ProductBrief` from the
  `AnalysisRequest` (§3.1). If resolution fails, it routes straight to END with an error and no agent
  runs.
- The four agents run **in parallel in one superstep**; `collect` waits for all four.
- `collect` is deterministic. It fills missing reports with `status="failed"`, runs a final validation,
  builds `SituationAnalysis`, and persists it (§7).
- All nodes are `async`.
- Compile with the SQLite checkpointer (`langgraph-checkpoint-sqlite`) at `data/db/agent_checkpoints.sqlite`.
  `thread_id = run_id`.

### 5.2 State

AnalysisState and its report reducer are defined once in [state.py](state.py).
Each agent writes its own report key.

`merge_dict = lambda a, b: {**(a or {}), **(b or {})}`. Parallel nodes write different keys of the same
channel, so a reducer is **required** (LangGraph raises `InvalidUpdateError` otherwise).

---

## 6. Agent specifications

### 6.0 Rules for all four agents

1. **Agent loops only where the search path is unknown.** Competition and trends use a bounded tool loop
   (`create_agent` + `response_format`). Baseline and feedback are deterministic pipelines with targeted
   structured LLM calls.
2. **IDs and sources are assigned by code.** LLM outputs reference temporary keys that code maps to
   `Source.id` / `Finding.id`.
3. **Citation validation (`validation.py`)**: each `source_id` must resolve, and each source needs a
   non-empty `excerpt`. Failing findings are **dropped and counted** in `stats.dropped_findings`, never
   repaired by the LLM.
4. **Numbers are never invented.** A `quantity` must come from a structured record (ontology/SQL), or be
   computed by code, or its number string must appear in the cited web `excerpt`. Otherwise drop the
   quantity, keep the qualitative claim and lower `confidence`.
5. **Failure isolation.** Catch exceptions and timeouts inside each node and return
   `status="failed"`/`"partial"` with `errors`. One failing agent must never stop the run.
6. **Budgets** from `config.py`: `max_tool_calls`, `timeout_s`, `max_pages_scraped` per agent.
7. **Model tiers**: `LLM_STRONG` for the competition/trends synthesis; `LLM_CHEAP` for extraction and
   labeling.
8. **`router.py`** holds a static table: data need → tool (`sql_rag` | `graph_rag` | `web_search`). Agents
   ask the router, so swapping a data source is a one-line change.
9. **Prompts** live in `prompts/<agent>_<step>.md` and always include: role, the brief, the taxonomy, the
   one-claim-per-finding rule, the citation rule, and the stopping rule.
10. **Region scoping is mandatory on every data call.** Every knowledge-layer call passes
    `brief.regions` or `brief.markets`, and every web call uses `brief.search_locale`. Each `Finding`
    records its region in `quantity.qualifier` or `subject` where it is region-specific (e.g. a price or a
    spec variant). Findings that hold for all regions stay unqualified. A test asserts that no tool call
    is made without region scoping (§9).
11. **`focus_areas` narrows the work, it doesn't filter the evidence.** Agents spend their search budget
    on the focus areas first, but they keep any strong finding outside them (e.g. a dominant feedback
    theme).

### 6.1 `baseline_agent` (no web)

1. Code: `brief.reference_model.attributes` (already loaded by `resolve_request`) → one finding per
   attribute value (`subject=<model_code>`, e.g. `"G60"`, `polarity="neutral"`, quantity from the record).
   No LLM.
2. Code: `sales_volume([model_code, *portfolio], markets=brief.markets)` → computed findings: volume per
   market and region, period-over-period change, share of portfolio volume (`attribute` = closest
   Business attribute, or `unmapped:sales_volume`).
3. Code: `list_portfolio(segment, regions=brief.regions)` → sources.
4. LLM (cheap, structured): portfolio positioning findings, e.g. gaps or overlaps between the new product
   and existing models, citing portfolio sources only.
- `stats`: `n_attributes`, `n_portfolio_models`, `total_units`.

### 6.2 `competition_agent`

1. Code: use `brief.competitors` (resolved per region). The competitor set can differ by region; tag each
   competitor with the regions it's sold in. If the list is empty, run one web step per region that
   proposes up to `MAX_COMPETITORS` competitors of the reference model in that region, with sources.
2. Code: the ontology attribute values for each competitor model → findings (`subject=<model>`).
3. **Fan-out per competitor** with LangGraph `Send` (an internal subgraph), max `MAX_COMPETITORS`. Each
   sub-run is a bounded tool loop with `web_search` + `scrape_url`. It fills taxonomy attributes in
   `focus_areas` that the ontology lacks or that are older than `STALE_AFTER_DAYS`. Prefer manufacturer
   spec pages and reputable reviews; one claim per finding; quantities only if they're on the page.
   Searches use the locale of the region the competitor is sold in, and region-specific values (price,
   spec variant) record the region.
4. Code: merge, dedupe by `(subject, attribute, quantity)`.
- `stats`: `n_competitors`, `n_pages_scraped`, `n_from_ontology`, `n_from_web`.

### 6.3 `feedback_agent` (deterministic, LLM only for labeling)

1. Code: `get_feedback_items(FeedbackFilter(models=[model_code], markets=brief.markets))`. If more than
   one region is requested, cluster all items together but compute per-region shares, so a theme that is
   strong only in one region stays visible.
2. `tools/feedback_stats.py`: dedupe exact and near duplicates (normalized text + embedding cosine
   > 0.95) → embed → cluster (HDBSCAN; or KMeans with k chosen by silhouette over 4–20).
3. LLM (cheap, structured, parallel per cluster): given ≤ 8 representative texts (closest to the
   centroid), return the taxonomy `attribute`, `polarity` and a one-sentence `claim`.
4. Code: `weight = cluster_size / n_items`. **Counts and shares are computed, never LLM-estimated.**
   Sources = the representative items (`kind="feedback"`, excerpt = verbatim text).
5. Code: per-market / per-channel shares into `stats` when those fields exist.
- `stats`: `n_items`, `n_after_dedupe`, `n_clusters`, `noise_share`.

### 6.4 `trends_agent`

1. Code: `search_documents(<brief-derived queries>, kinds=["study","report"], regions=brief.regions)` →
   candidate sources from the knowledge layer first.
2. Bounded tool loop (strong model) with `search_documents` + `web_search` + `scrape_url`. Goal: 3–6
   product and global trends (technology, regulation, market, customer behavior) relevant to the brief.
3. Each trend becomes one or more findings on **taxonomy attributes** (e.g. "megawatt charging rollout"
   → `fast_charging`, `polarity="demand"`), with horizon in `quantity.qualifier` or in the claim:
   `now` | `1-2y` | `3y+`.
- `stats`: `n_trends`, `n_pages_scraped`, `n_from_knowledge`, `n_from_web`.

### 6.5 `tools/web_search.py`

The SearchBackend protocol is defined once in
[tools/web_search.py](tools/web_search.py), including the optional research locale.

- Default: **Firecrawl** (search with markdown scrape options; separate scrape for known URLs). The
  backend is selectable via `SEARCH_BACKEND=firecrawl|openai|brave`; only Firecrawl must be implemented
  now.
- **Every call goes through an on-disk cache** at `data/processed/web_cache/` (key = normalized query or
  canonical URL). `OFFLINE_MODE=true` serves only from cache and fails when a key is missing. This gives
  reproducible demos and saves credits.
- `Source.id = "web:" + sha1(canonical_url)[:8]`, so the same page is never stored twice.
- Expose `web_search` and `scrape_url` as LangChain tools whose results show the source ids, so the model
  can cite them.

---

## 7. Service API (`service.py`) — what the API layer calls

```python
async def list_models() -> list[SupportedModel]
    # registry entries (§4.5): model_code, name, regions; feeds the UI dropdowns

async def resolve(request: AnalysisRequest) -> ProductBrief
    # dry run of resolve_request: lets the UI show the resolved brief (segment, competitors, focus areas)
    # before launching; raises a validation error for an unknown model code or region

async def start_analysis(request: AnalysisRequest, brief_override: ProductBrief | None = None) -> str
    # creates run_id, launches the graph in the background (asyncio task), returns run_id immediately;
    # brief_override = the PM-corrected brief from resolve(), used instead of re-resolving

async def get_analysis(run_id: str) -> RunStatus
    # RunStatus: run_id, state: "running"|"done"|"failed",
    #            agents: dict[AgentName, Literal["pending","running","ok","partial","failed"]],
    #            analysis: SituationAnalysis | None

async def stream_analysis(run_id: str) -> AsyncIterator[dict]
    # node start/finish events from graph.astream(stream_mode="updates"), for live progress in the UI

async def explain(run_id: str, question: str, finding_id: str | None = None) -> Explanation
    # Explanation: answer: str, cited_ids: list[str]
```

**`explain` is how the app backs its arguments.** It loads the stored `SituationAnalysis` and restricts
the context to the target finding (or, without one, retrieves the relevant findings by embedding
similarity), together with their sources. The strong model then answers **only** from that context and
cites finding/source ids in every sentence; the answer goes through the same validator. If the evidence
doesn't support an answer, it says so and names what is missing.

**Persistence:** `collect` writes the `SituationAnalysis` JSON to
`data/processed/analyses/<run_id>.json`. It also calls `knowledge.ontology.store_findings(analysis)` if
that function exists (optional contract). `ontology_persistence` records `skipped`,
`stored`, or `failed`, including the error on failure; run status and completion
events expose the same outcome. `stored` means the configured hook completed,
not graph acceptance or human approval. The current read bridge returns `False`
because its services have no `store_findings` implementation. Analysis DTOs still
need explicit translation into a validated graph candidate. `FileCandidateStore`
provides separate local acceptance for non-Requirement candidates; requirement and
human review writes need their own operations.

---

## 8. Configuration (`config.py`, keys added to `.env.example`)

```
OPENAI_API_KEY=
LLM_STRONG=                 # a current OpenAI flagship model id (check, don't guess)
LLM_CHEAP=                  # a current small OpenAI model id
EMBEDDING_MODEL=text-embedding-3-small
FIRECRAWL_API_KEY=
SEARCH_BACKEND=firecrawl
OFFLINE_MODE=false
MAX_COMPETITORS=6
STALE_AFTER_DAYS=365
MAX_TOOL_CALLS_PER_AGENT=20
AGENT_TIMEOUT_S=180
MAX_PAGES_SCRAPED_PER_AGENT=25
```

Models are created via `init_chat_model("openai:<id>")`, so a provider switch is a config change.

---

## 9. Tests (`tests/`)

- **`tests/fakes/`**: in-memory implementations of every §4 contract, with synthetic data: a fake
  reference model with code `TEST01`, 3 portfolio models, 2 regions (`EU`, `CN`) with partly different
  competitor sets (4 competitors total), ~150 feedback items spread over both regions with 5–6 planted
  themes (one present only in `CN`), and 5 study chunks. Names are clearly fake (e.g. `Competitor A`).
  These remain the isolated agent-test backend. Separate knowledge tests exercise
  snapshot/Neon/combined adapters and the real v1 bridge with synthetic inputs.
- **`test_agent_tools.py`** (existing file, extend): tool wrappers return the expected `Source` format;
  the web cache hits on the second call; offline mode raises on a cache miss.
- **Add:**
  - `resolve_request`: `TEST01` + `["EU"]` resolves segment and EU competitors; an unknown model code or
    region fails fast and no agent runs; no regions = all regions the model supports;
  - registry: a model outside the registry is rejected, and so is a model–region combination the
    registry doesn't list (the fakes include one model that exists only in `CN`);
  - region scoping: a spy on all §4 calls and web calls asserts that every call carries regions,
    markets or a locale, and a `["CN"]` run never queries EU-only competitors;
  - the CN-only feedback theme appears with its per-region share in a `["EU", "CN"]` run;
  - validator drops dangling citations and unsupported quantities;
  - feedback weights equal the cluster shares and sum to 1 − noise share;
  - planted feedback themes are recovered;
  - forcing `trends_agent` to raise still yields a `SituationAnalysis` with `reports["trends"].status == "failed"`;
  - every `source_id` in a full offline run resolves;
  - `explain` cites only ids in the target's evidence.

---

## 10. Original build order (each step ends runnable)

The orchestration code and synthetic tests are implemented. This list preserves
the original sequence; it is not the remaining ontology plan. See
[the project plan](../../../docs/project-plan.md#implementation-sequence) for the
current requirement/review milestones and data boundary.

1. Schemas (§3, proposed in `bmwow/agent/models/evidence.py`), `state.py`, `config.py`, `llm.py`, fakes.
2. `supervisor.py` with `resolve_request`, 4 stub nodes and `collect`, plus
   `service.resolve/start_analysis/get_analysis`. Runs end to end on fakes.
3. `validation.py`, `router.py`, `tools/graph_rag.py`, `tools/sql_rag.py`.
4. `baseline_agent`, then `feedback_agent` (+ `feedback_stats.py`).
5. `tools/web_search.py` (Firecrawl + cache + offline), then `competition_agent` (with `Send` fan-out),
   then `trends_agent`.
6. `service.explain`, `stream_analysis`, persistence.
7. Tests green; record a web cache for the demo.

---

## 11. Current integration decisions and remaining items

- The §4 read interfaces exist in `bmwow.knowledge`, with v1 reexports and a thin
  module bridge. Ontology v0.2.0 and the existing v1 read records are unchanged.
- The combined service reads private sales/study snapshots and Neon feedback/aspects.
  Catalog staging accepts closed reviewed bundles; full PDF extraction remains pending.
- Graph taxonomy uses canonical Features and configured feature keys. The YAML
  fallback applies only when the optional backend contract returns `None`, not an
  authoritative empty taxonomy. The initial curation template needs Feature review.
- Feedback `EU` groups member countries; source sales/study Europe retains separate
  market IDs with unknown country populations. Source-region sales context still
  needs routing alongside the baseline's existing feedback-country sales selector.
- F70/G60/G68/G70 identities are explicit. Marketing names, segments, powertrains,
  sold regions, and exact Feature mappings still need team review. G60/G68 sales
  remain one combined group and do not establish a variant relationship.
- Competitor identities, `COMPETES_WITH` links, and curated sale regions need sources;
  evidence coverage alone cannot establish where a competitor is sold.
- The analysis write hook is unconnected. Choose the analysis-to-graph conversion
  before using local candidate acceptance; authenticated requirement/review services
  and shared graph persistence remain later work.
- Whether runs without a predecessor (a brand-new model line) are in scope. If yes, `model_code` becomes
  optional and `segment` becomes a required input.
