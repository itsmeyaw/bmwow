# AGENT_SPEC — `src/agent/`: Situation Analysis Agents

> **For Claude (the builder).** This spec covers **only `src/agent/`**: the four situation-analysis agents
> (`baseline_agent`, `competition_agent`, `feedback_agent`, `trends_agent`), their tools, and the service
> functions `src/api/` calls. Everything else in the repo is built by teammates.
>
> - **Do not implement** `src/knowledge/`, `src/models/`, `src/api/` or `frontend/`. §4 lists the
>   functions and schemas `agent/` needs from them. Code against those contracts. Until they exist, use
>   the stubs in `tests/fakes/` (§9).
> - **The repo structure and the data sources are suggestions, not fixed.** The team is still cleaning
>   the data and defining file structures. Keep every data access behind the interfaces in §4, so a
>   changed source or schema means changing one adapter, never an agent.
> - **The contracts in this file are fixed** (schemas, node names, output envelope, service functions).
>   Code snippets are illustrative. Check the installed versions of LangGraph, LangChain,
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

## 2. Folder layout (`src/agent/`)

Adapted from the team's suggested layout; files marked *(new)* are additions this spec needs.

```
src/agent/
├── __init__.py
├── service.py            (new) public entry points for src/api/  (§7)
├── supervisor.py         builds the analysis graph: fan-out to 4 agents, fan-in collect (§5)
├── state.py              (new) AnalysisState + reducers (§5.2)
├── config.py             (new) env, model tiers, budgets (§8)
├── llm.py                (new) model factory: strong / cheap / embeddings
├── router.py             maps an agent's data needs to SQL, ontology or web tools (§6.0)
├── validation.py         (new) citation + quantity checks (§6.0)
├── synthesizer.py        NOT in scope (downstream requirement synthesis); leave untouched
├── nodes/                (new) one module per agent
│   ├── baseline.py
│   ├── competition.py
│   ├── feedback.py
│   └── trends.py
├── prompts/              (new) one .md prompt per LLM step, loaded at runtime
└── tools/
    ├── graph_rag.py      wraps src/knowledge/ontology.py contracts as LangChain tools
    ├── sql_rag.py        wraps src/knowledge/sql_client.py contracts as LangChain tools
    ├── web_search.py     (new) Firecrawl search + scrape behind SearchBackend, with cache (§6.5)
    └── feedback_stats.py (new) dedupe / embed / cluster feedback (deterministic, §6.3)
```

`supervisor.py` must also expose the compiled graph as a **subgraph**, so the downstream pipeline can
mount it as one node later.

---

## 3. Output contract (what `structure_agent` receives)

Put these in `src/models/evidence.py`. If a teammate owns that file, **propose** them there and don't
duplicate them in `agent/`. Field names are fixed; add fields only as optional ones.

```python
Confidence = Literal["low", "medium", "high"]
AgentName = Literal["baseline", "competition", "feedback", "trends"]


class Source(BaseModel):
    id: str  # "kg:<node_id>", "sql:<query_hash>", "web:<url_hash8>", "fb:<item_id>"
    kind: Literal["ontology", "sql", "web", "feedback"]
    ref: str  # node id / SQL text / URL / feedback item id
    title: str = ""
    excerpt: str  # exact text or rendered row the claim relies on (<= 1200 chars). REQUIRED.
    retrieved_at: datetime


class Quantity(BaseModel):
    value: float
    unit: str  # canonical: "km", "kW", "min", "EUR", "units", "share", ...
    qualifier: str = ""  # "WLTP", "10-80%", "2024 DE", "median", ...


class Finding(BaseModel):
    id: str  # "F-<agent>-<n>", assigned by code, never by the LLM
    agent: AgentName
    attribute: str  # taxonomy key (§4.3) or "unmapped:<proposed_name>"
    claim: str  # one sentence, one claim
    polarity: Literal["positive", "negative", "neutral", "demand"]  # demand = customers want more
    subject: str  # whose attribute: "previous_model", "<competitor model>", "market", "customers"
    quantity: Quantity | None = None
    source_ids: list[str]  # >= 1, must resolve to Sources in the same report
    confidence: Confidence
    weight: float = 1.0  # set by code only (e.g. share of feedback items)


class AgentReport(BaseModel):
    agent: AgentName
    status: Literal["ok", "partial", "failed"]
    findings: list[Finding]
    sources: list[Source]
    summary: str  # <= 120 words, for the UI
    stats: dict[str, float | int] = {}
    errors: list[str] = []


class SituationAnalysis(BaseModel):  # the hand-off object
    run_id: str
    request: AnalysisRequest  # what the PM typed (§3.1)
    brief: ProductBrief  # what the run actually used
    reports: dict[
        AgentName, AgentReport
    ]  # all four keys always present (failed agents: status="failed")
    created_at: datetime
```

### 3.1 Input: `AnalysisRequest` → resolved `ProductBrief`

The PM enters only this:

```python
class AnalysisRequest(BaseModel):
    model_code: (
        str  # reference model; must be in the model registry (§4.5): currently G60, F70, G68
    )
    regions: list[str] | None = None  # optional, codes from §4.4, e.g. ["EU"], ["EU", "US"];
    # None/empty = all regions the model supports in the registry
```

The `resolve_request` node (§5.1) turns it into the brief every agent works from:

```python
class ProductBrief(BaseModel):
    reference_model: ModelNode  # from get_model(model_code): name, segment, powertrain, attributes
    regions: list[str]  # validated region codes
    markets: list[str]  # countries/markets each region expands to (§4.4)
    segment: str  # from reference_model
    competitors: list[ModelNode]  # list_competitor_models(segment, regions)
    focus_areas: list[str] = []  # empty = all areas; the PM may set them in a corrected brief
    search_locale: dict[str, str]  # region -> {"country": ..., "lang": ...} for web search
```

Resolution rules:

- **`model_code` not in the registry → fail fast** with a clear error that lists the valid codes. Don't
  guess a model.
- **Unknown region → fail fast** and list the valid codes.
- **Model–region combination not in the registry → fail fast**, e.g. a model that is only sold in `CN`
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

### 4.1 `src/knowledge/ontology.py` (graph)

```python
def get_model(model_code: str) -> ModelNode | None              # incl. attributes; None if unknown
def list_portfolio(segment: str | None = None, regions: list[str] | None = None) -> list[ModelNode]
def list_competitor_models(segment: str, regions: list[str], names: list[str] | None = None) -> list[ModelNode]
def get_attribute_values(model_id: str, attributes: list[str] | None = None) -> list[AttributeValue]
def get_feedback_items(filters: FeedbackFilter) -> list[FeedbackItem]       # paginated / iterable OK
def search_documents(query: str, kinds: list[str] | None = None, regions: list[str] | None = None,
                     k: int = 10) -> list[DocChunk]           # studies, reports
```

Minimum fields the agents rely on (placeholder, the team may extend):

```python
class AttributeValue(BaseModel):
    node_id: str
    attribute: str
    value: float | str
    unit: str | None
    source_note: str = ""


class ModelNode(BaseModel):
    node_id: str
    model_code: str | None
    name: str
    brand: str
    segment: str
    powertrain: str | None
    regions: list[str] = []
    attributes: list[AttributeValue] = []


class FeedbackItem(BaseModel):
    item_id: str
    text: str
    channel: str
    market: str | None
    date: date | None
    rating: float | None
    model: str | None


class DocChunk(BaseModel):
    node_id: str
    doc_title: str
    text: str
    url: str | None
    published: date | None
    regions: list[str] = []


class FeedbackFilter(BaseModel):
    models: list[str] = []
    markets: list[str] = []
    since: date | None = None
    limit: int | None = None
```

### 4.2 `src/knowledge/sql_client.py` (relational)

```python
def sales_volume(models: list[str], markets: list[str] | None = None,
                 period_from: str | None = None, period_to: str | None = None) -> list[SalesRow]
class SalesRow(BaseModel): model: str; market: str; period: str; units: int
```

Every function result becomes a `Source` in the agent. Ontology results map to `kind="ontology"` with
`ref=node_id`; SQL results map to `kind="sql"` with `ref` = the query parameters and `excerpt` = the
rendered rows.

### 4.3 Attribute taxonomy

Agents map every finding to a taxonomy attribute. Load it from `src/knowledge/ontology.py` if the
ontology defines it; otherwise fall back to `src/agent/taxonomy.yaml`, seeded from the brief:

```yaml
Exterior:          [iconic_design, exterior_colors, sport_wheels, easy_entry]
Interior:          [premium_feel, comfortable_seats, seat_ventilation, heated_seats, rear_space, flexible_storage, easy_child_seat_fit]
Powertrain:        [real_world_range, fast_charging, efficiency, long_battery_life, smooth_ride, dynamic_handling]
Digital_UX:        [intuitive_ux, clear_displays, physical_controls, reliable_software, fast_app_response, easy_updates, personalization, clear_navigation, great_sound]
Driver_assistance: [safety, easy_parking]
Business:          [affordable, low_running_costs, simple_maintenance, sustainability, data_privacy]
```

Findings that fit no attribute get `attribute="unmapped:<name>"` and are kept. Downstream decides what
to do with them.

### 4.4 Regions

Load the list from the knowledge layer if it defines one; otherwise fall back to `src/agent/regions.yaml`.
Each region maps to markets (as used in sales and feedback data) and to a web-search locale:

```yaml
EU: { markets: [DE, FR, IT, ES, NL, ...], search: { country: de, lang: en } }
US: { markets: [US],                      search: { country: us, lang: en } }
CN: { markets: [CN],                      search: { country: cn, lang: zh } }
```

These values are placeholders. The team decides the real region list and market codes, matching the
data.

### 4.5 Model registry (the only models the app supports)

Data exists only for three reference models, so the agent rejects any other model. The registry is
loaded from the knowledge layer if it offers `list_supported_models()`; otherwise from
`src/agent/models.yaml`:

```yaml
G60: { name: "5 Series Sedan",                  regions: [EU, US, CN] }   # regions: TO CONFIRM with the data
F70: { name: "1 Series",                        regions: [EU] }           # regions: TO CONFIRM with the data
G68: { name: "5 Series Sedan long wheelbase",   regions: [CN] }           # regions: TO CONFIRM with the data
```

- **Names and regions are placeholders** until the team confirms them against the data. The builder
  must not fill them in from general knowledge.
- A model's `regions` is the list of regions with data for that model. Resolution (§3.1) validates the
  requested regions against it.
- Adding a model later = one registry entry plus its data. No code change.

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

```python
class AnalysisState(TypedDict, total=False):
    run_id: str
    request: AnalysisRequest
    brief: ProductBrief
    resolve_error: str | None
    reports: Annotated[dict[AgentName, AgentReport], merge_dict]  # each agent writes its own key
    analysis: SituationAnalysis
```

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

```python
class SearchBackend(Protocol):
    async def search(
        self, query: str, limit: int = 5
    ) -> list[Source]: ...  # excerpt = best-matching chunk
    async def scrape(self, url: str) -> Source: ...  # full page markdown → chunked
```

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

## 7. Service API (`service.py`) — what `src/api/routes.py` calls

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
that function exists (optional contract), so findings become nodes linked to their source nodes for the
traceability map.

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
  Agents are built and tested against these until the real `knowledge/` exists.
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

## 10. Build order (each step ends runnable)

1. Schemas (§3, proposed in `src/models/evidence.py`), `state.py`, `config.py`, `llm.py`, fakes.
2. `supervisor.py` with `resolve_request`, 4 stub nodes and `collect`, plus
   `service.resolve/start_analysis/get_analysis`. Runs end to end on fakes.
3. `validation.py`, `router.py`, `tools/graph_rag.py`, `tools/sql_rag.py`.
4. `baseline_agent`, then `feedback_agent` (+ `feedback_stats.py`).
5. `tools/web_search.py` (Firecrawl + cache + offline), then `competition_agent` (with `Send` fan-out),
   then `trends_agent`.
6. `service.explain`, `stream_analysis`, persistence.
7. Tests green; record a web cache for the demo.

---

## 11. Open items (ask the team, don't guess)

- Final data sources and schemas behind §4 (the team is cleaning the data now). Only adapters should
  change when they land.
- Whether the taxonomy lives in the ontology or in `taxonomy.yaml`.
- The real region list and how regions map to the market codes used in sales and feedback data (§4.4).
- Names and supported regions for G60, F70 and G68 in the model registry (§4.5), confirmed against the
  data.
- Whether the data links each competitor to the regions it's sold in, or whether that has to be derived.
- Whether runs without a predecessor (a brand-new model line) are in scope. If yes, `model_code` becomes
  optional and `segment` becomes a required input.
- Whether `knowledge.ontology.store_findings` will exist for the traceability map.
- Who owns `src/models/evidence.py`. If the team prefers, the §3 schemas can live in `src/agent/` and be
  re-exported.