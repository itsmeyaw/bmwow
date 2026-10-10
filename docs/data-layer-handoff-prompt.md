# Prompt: build the data layer (SQL + ontology) behind the situation-analysis agents

You are implementing the **data layer** of the BMWow hackathon project: clean `raw_data/BMW-Data/` into
SQL, populate the ontology with the entities and links, and expose **one agent-facing interface** that
the situation-analysis agents in `src/agent/` already call. Read this whole prompt, then
`docs/ontology.md`, `docs/ontology-plan.md`, `AGENT_SPEC.md` §4 and `src/models/knowledge.py` before
writing code.

## 1. Context

- **Goal of the app:** BMW product managers turn ~1 billion findings into ~1,000 requirements into one
  car. A requirement is a customer-relevant attribute of a car (e.g. real-world range, seat
  ventilation), later quantified ("range: 600 or 700 km?").
- **Our step is the first one, situation analysis.** Four agents run in parallel for one reference
  model (`F70`, `G60`, …) and optional regions (`EU`, `CN`, `US`; none = all regions the model has data
  for):
  - `baseline`: previous model data (option list) + sales volume;
  - `competition`: competitors in the same segment and market (mostly web, since there is no competitor data);
  - `feedback`: customer feedback (frequency of likes, wants, defects per feature, per region);
  - `trends`: studies + web.
- **The agents never touch SQL or the graph directly.** They call the functions in §4 through an
  adapter (`src/agent/tools/knowledge.py`). Your job is to make those functions real. **Do not modify
  `src/agent/`**; if a contract below cannot be met, stop and report why instead of changing the agents.
- **Keep the ontology v0.2 design** (`backend/bmwow/ontology/`). Everything here builds on it; do not
  redesign object or link types.

## 2. Storage split (agreed)

**SQL holds the facts and volumes; the ontology holds the things and how they connect.** Nothing is
stored twice: ontology nodes reference SQL rows through `SqlLocator`, never by copying the values.

| Data | Store | Notes |
|---|---|---|
| Sales volumes (`sales_volumes.xlsx`) | SQL | Per model sheet × region × year, incl. 2030 |
| Feedback rows (`*_feedback_hackathon.xlsx`) | SQL | ~13k rows, with source, country, engine, type and VFC classification |
| Customer studies (`F70_G60_G68_G70_customer_studies.xlsx`) | SQL | CN/EU and US sheets, with means and response shares per question |
| Option-list values (`*_OptionList.PDF`) | SQL | Extracted prices, standard/optional equipment and technical values, each with page and original text |
| Models, variants (`G68 IS_VARIANT_OF G60`), brand, segment, powertrains | Ontology | `VehicleModel` |
| Regions/markets and their country codes | Ontology | `Market` (country mapping must be configured, never guessed) |
| Features / taxonomy, aliases, **VFC category → Feature mapping** | Ontology | `Feature`; VFC strings stay raw classifications and reviewable aliases |
| Option and package identities | Ontology | `CatalogItem` (+ `INCLUDES`), with values stored in SQL |
| Competitor relations | Ontology | `COMPETES_WITH`, scoped to market and segment, only with evidence |
| Agent findings → evidence → source row (after a run) | Ontology | via `store_findings`; `Evidence` locators point to SQL rows |

Use **SQLite** at `data/db/bmwow.sqlite` unless the team has already chosen another engine. Keep the
loaders idempotent: rerunning them rebuilds the same tables. Raw BMW data stays gitignored; do not
commit originals or derived real-data samples.

## 3. Facts about the raw data (verified; handle them explicitly)

1. **Models in the data:** option list + feedback files exist for **F70, G60, G70**. **G68** appears
   only in the customer studies and in the combined sales sheet `G60_G68`. The current agent model
   registry lists G60, F70, G68 (see open decision D1).
2. **Feedback has several rows per feedback item:** one row per classification (F70: 4,076 rows but
   2,128 unique IDs). Store a `feedback_item` table (one row per ID: text, source, country, engine,
   model) and a `feedback_classification` table (ID, feedback type, VFC level 2, VFC level 3). The
   **same item can have different feedback types per row** (e.g. Likes + Difficult to Use).
   Frequencies are counted per item, never per row.
3. **Feedback type** ∈ {Likes, Wants, Defect, Difficult to Use, null}. `no_class_found` and null VFC
   values are kept, never dropped. They are the input for clustering on the agent side.
4. **Feedback countries are mostly US (G60, G70) and GB/JP (F70). There is no Chinese feedback.** JP,
   KR, AU and CA are not in any region yet (D2).
5. **Sources are anonymized as Source A–D** (D3). Store them as given.
6. **Sales are region-level (`EU`, `CN`, `US`)** with `volume_2024`, `volume_2025` and `volume_2030`.
   2030 is `source_reported_future` (unknown method), not an actual. Explicit zeros are kept (F70 CN/US
   = 0). The `G60_G68` sheet is **one combined group**: never copy it to both models or split it.
7. **Customer studies:**
   - `CN_EU_2025` has means per model (with a `G70` column for both CN and EU) and no scale bounds or sample sizes.
   - `US_2025` has response shares per question and category; `Sample total = 1` is a normalized total, not a count.
   - Keep the question, response category, statistic type and region on every row.
8. **Option lists** are German catalogs (July 2026). They prove availability only for Germany/EU, not
   for US or CN. Keep the original German text, page number, column header, unit and footnote for every
   extracted value. Configuration alternatives are separate claims (standard 11 kW / optional 22 kW are
   two rows, not a range). A real interval (e.g. WLTP range depending on configuration) is one row with
   min/max. Spot-check extracted numbers visually against the PDF.

## 4. The interface the agents call (the contract)

Expose these functions with **exactly these names and parameters**, sync or async. The agent adapter
imports them from `src/knowledge/ontology.py` and `src/knowledge/sql_client.py`, so create those two
modules as thin shims that re-export your implementation (e.g. from `backend/bmwow/knowledge/`). Which
store backs each function is your choice; the split in §2 is the guide. Return objects (or dicts) with
at least the fields listed; extra fields are ignored. Record types are defined in
`src/models/knowledge.py`; optional fields marked **(new)** are ones the agent side will add, so
include them.

**`src/knowledge/ontology.py`**

```python
def list_supported_models() -> list[dict]
    # [{"model_code": "G60", "name": "...", "regions": ["EU","US","CN"]}, ...]
    # regions = regions for which the data has this model (feedback, sales or studies)

def list_regions() -> dict[str, dict]
    # {"EU": {"markets": ["DE","GB","SE",...], "search": {"country": "de", "lang": "en"}}, ...}
    # markets = country codes as used in the feedback data; mapping from D2

def get_model(model_code: str) -> ModelNode | None
    # node_id, model_code, name, brand, segment, powertrain, regions: list[str],
    # attributes: list[AttributeValue]   ← from the option list (SQL), mapped to taxonomy keys
    # None if unknown. Accept the model code, node id or name.

def list_portfolio(segment: str | None, regions: list[str] | None) -> list[ModelNode]
    # BMW models in the segment that are sold in any of the regions

def list_competitor_models(segment: str, regions: list[str], names: list[str] | None = None) -> list[ModelNode]
    # only competitors backed by evidence/curation; [] is a valid answer (the agent then searches the web)

def get_attribute_values(model_id: str, attributes: list[str] | None = None) -> list[AttributeValue]
    # AttributeValue: node_id, attribute (taxonomy key or "unmapped:<snake_case>"), value (float|str),
    # unit, source_note (e.g. "WLTP", "standard", "optional, 1,200 EUR"), as_of (catalog date)

def get_feedback_items(filters: FeedbackFilter) -> list[FeedbackItem]
    # filters: models (model codes), markets (country codes), since, limit
    # FeedbackItem: item_id, text, channel (= Source A–D), market (= country), date, rating, model,
    #   engine_type (new), classifications (new): [{"feedback_type", "vfc_category", "vfc_issue",
    #   "attribute"}]  ← attribute = taxonomy key from the VFC→Feature mapping, or None
    # one FeedbackItem per feedback ID (not per row)

def search_documents(query: str, kinds: list[str] | None, regions: list[str] | None, k: int = 10) -> list[DocChunk]
    # studies/reports as text chunks; [] is fine while there are no text documents

def get_taxonomy() -> dict[str, list[str]]
    # {"Powertrain": ["real_world_range", "fast_charging", ...], ...} from the Feature nodes;
    # seed it from src/agent/taxonomy.yaml (the keynote's attribute list)

def get_study_scores(models: list[str], regions: list[str]) -> list[dict]          # (new)
    # [{"model", "region", "study", "question", "statistic" ("mean"|"share"), "response_category",
    #   "value", "sample_note", "source_ref"}]  ← no harmonization across studies

def store_findings(analysis) -> None                                               # optional
    # write SituationAnalysis findings as Signals/Evidence linked to the cited SQL rows
```

**`src/knowledge/sql_client.py`**

```python
def sales_volume(models: list[str], markets: list[str] | None = None,
                 period_from: str | None = None, period_to: str | None = None) -> list[SalesRow]
    # SalesRow: model, market, period ("2024"|"2025"|"2030"), units,
    #   status (new: "actual"|"source_reported_future"), source_group (new, e.g. "G60_G68")
    # The data is region-level: `markets` may contain region codes or country codes; map country codes
    # to their region and return market = region code. A G60 or G68 query returns the combined
    # G60_G68 rows with source_group set, unsplit.
```

**Every result must be traceable:** each returned record carries a stable id (`node_id` / `item_id`)
that resolves to an ontology node or SQL row, so the agents can cite it as a source.

## 5. Rules

- **Never invent data.** Unknown means `null`. Don't fill model names, regions, segments or competitor
  sets from general knowledge.
- **Open decisions (§6) live in one config file** (e.g. `backend/bmwow/knowledge/config.yaml`) with
  `TODO(team)` markers, not hard-coded in queries.
- The **VFC → Feature mapping** may be drafted automatically (string similarity or an LLM proposal), but
  every mapping row records `status: proposed | reviewed`. Unmapped VFC categories stay unmapped.
- Keep the ontology validation green (`bmwow-validate`, existing tests) and run Ruff.

## 6. Open decisions: ask the team, don't guess

- **D1 Models:** should the registry be F70, G60, G70 (with G68 = G60 long-wheelbase variant for CN), or
  F70, G60, G68?
- **D2 Country → region mapping:** e.g. GB, SE, DK, FR, FI, NO, ES → EU; CA → US? What about JP, KR, AU
  (drop or add an "other" region)?
- **D3 Sources A–D:** what are they (survey, dealer, app, forum…)? This drives source weighting later.
- **D4 Segment labels** per model (needed for portfolio and competitor queries).

## 7. Done when

1. Loaders build all SQL tables from `raw_data/` in one command; a rerun gives identical row counts.
2. Feedback counts per item match the unique IDs (F70: 2,128; G60: 4,000; G70: 4,000).
3. `sales_volume(["F70"], ["DE"])` returns EU rows; `sales_volume(["G68"])` returns `G60_G68` rows with
   `source_group` set; 2030 rows have `status="source_reported_future"`.
4. `get_feedback_items(FeedbackFilter(models=["G60"], markets=["US"]))` returns one item per ID with all
   its classifications.
5. Every function in §4 has a test on a small synthetic fixture (no real BMW data in tracked files).
6. The agent test suite still passes:
   `.venv/bin/python -m pytest -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function tests --ignore=tests/ontology`
   and, with `KNOWLEDGE_BACKEND=real`, `python -m scripts.run_analysis scripts/example_request.json`
   (using a real model code) runs end to end.
7. A short `docs/data-layer.md`: tables, ontology population, function → store mapping, and the status
   of D1–D4.

**Out of scope:** the agents in `src/agent/`, prompts, web scraping, prioritization, frontend.
