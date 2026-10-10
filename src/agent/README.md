# `src/agent/` — situation analysis agents

Implements [AGENT_SPEC.md](../../AGENT_SPEC.md). Four agents run in parallel and hand a validated
`SituationAnalysis` (schemas in `src/models/evidence.py`) to the downstream `structure_agent`.

```
service.py        list_models / resolve / start_analysis / get_analysis / stream_analysis / explain / aclose
                  ← src/api calls these
supervisor.py     graph: START → resolve_request → 4 agents (one superstep) → collect → END; a resolve error
                  goes straight to END; build_subgraph() for mounting
resolve.py        AnalysisRequest (model code + optional regions) → ProductBrief; deterministic, no LLM
registry.py       model registry + region list (knowledge layer if it offers them, else models.yaml /
                  regions.yaml); fail-fast request checks
nodes/            baseline, competition (Send fan-out per competitor), feedback, trends; common.py = context,
                  failure isolation, bounded tool loop
validation.py     citation + quantity + claim-number checks (drop and count, never repair)
router.py         data need → sql_rag | graph_rag | web_search (one-line source swaps)
tools/knowledge.py  the only coupling to src/knowledge (contract records + adapter); swap here when it lands
tools/web_search.py Firecrawl behind SearchBackend, on-disk cache, OFFLINE_MODE
tools/feedback_stats.py  dedupe → embed → HDBSCAN (KMeans fallback); all counts/shares computed here
prompts/          one .md per LLM step; _common_rules.md is included in each
```

## Run

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r pyproject.toml --extra dev
.venv/bin/python -m pytest                                   # fakes only, no keys needed
cp .env.example .env                                         # set OPENAI_API_KEY, LLM_STRONG, LLM_CHEAP, FIRECRAWL_API_KEY
KNOWLEDGE_BACKEND=fake .venv/bin/python -m scripts.run_analysis scripts/example_request.json
```

`KNOWLEDGE_BACKEND=fake` serves `tests/fakes/` until `src/knowledge/` exists; `real` (default) imports
`src.knowledge.ontology` and `src.knowledge.sql_client` (sync or async functions both work).

## Decisions worth knowing

- **Input** is an `AnalysisRequest`: `model_code` (G60, F70, G68) and optional `regions` (EU, CN, US);
  no regions = all regions the model has data for in the registry. Unknown codes/regions and unsupported model–region pairs raise `ResolveError` listing the valid choices,
  in `service.resolve` and already in `service.start_analysis` (before a run is created).
- **Region scoping**: portfolio, competitors and documents are queried with `brief.regions`, sales and
  feedback with `brief.markets`, web searches with the region's `search_locale` (cache key includes it).
  `get_model` / `get_attribute_values` address one model by id and are not region-scoped.
- **Competitors** are tagged with the requested regions they are sold in (no region data = all requested
  regions); each is researched in the locales of its regions.
- **Feedback with several regions**: one finding per theme over all items (weights sum to 1 − noise),
  plus one per theme and region (share of that region's items, citing that region's items only).
- **Brief additions** (optional fields): `region_markets` (region → markets) and `warnings` (shown to the PM).

- **Feedback shares** are relative to the *deduplicated* corpus, so cluster shares + `noise_share` = 1.
  Clusters that the LLM labels with the same (attribute, polarity) are merged into one finding.
- **`Quantity.origin`** (optional field): `record` (ontology/SQL value, must appear in the cited excerpt),
  `computed` (by code from stored data), `source_text` (must appear in a cited excerpt). Set by code only.
- **Web excerpts**: one `Source` per page (`web:<sha1(canonical_url)[:8]>`). LLM findings carry a verbatim
  `evidence_quote`; verified quotes become the page's excerpt, so excerpts contain what claims rely on.
- **LLM-written claims** may only contain numbers found in the cited excerpts; otherwise the finding is
  dropped (`stats.dropped_unsupported_numbers`).
- Reports list only the sources their findings cite.
- `AttributeValue.as_of` (optional) drives `STALE_AFTER_DAYS`; values without a date count as fresh.
