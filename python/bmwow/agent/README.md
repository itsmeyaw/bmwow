# `bmwow/agent/` — situation analysis agents

Implements [SPEC.md](SPEC.md). Four agents run in parallel and hand a validated
`SituationAnalysis` (schemas in `bmwow/agent/models/evidence.py`) to the downstream `structure_agent`.

```
service.py        list_models / resolve / start_analysis / get_analysis / stream_analysis / explain / aclose
                  ← the API layer calls these
supervisor.py     graph: START → resolve_request → 4 agents (one superstep) → collect → END; a resolve error
                  goes straight to END; build_subgraph() for mounting
resolve.py        AnalysisRequest (model code + optional regions) → ProductBrief; deterministic, no LLM
registry.py       model registry + region list (knowledge layer if it offers them, else models.yaml /
                  regions.yaml); fail-fast request checks
nodes/            baseline, competition (Send fan-out per competitor), feedback, trends; common.py = context,
                  failure isolation, bounded tool loop
validation.py     citation + quantity + claim-number checks (drop and count, never repair)
router.py         data need → sql_rag | graph_rag | web_search (one-line source swaps)
tools/knowledge.py  coupling to bmwow/agent/knowledge_bridge (thin bridge to bmwow.knowledge); swap storage behind it
tools/web_search.py Firecrawl behind SearchBackend, on-disk cache, OFFLINE_MODE
tools/feedback_stats.py  dedupe → embed → HDBSCAN (KMeans fallback); all counts/shares computed here
prompts/          one .md per LLM step; _common_rules.md is included in each
```

## Run

```bash
cd python                                                    # python/pyproject.toml + uv.lock
uv sync --locked
uv run pytest                                               # fakes/synthetic only, no keys needed
uv run python -m scripts.inspect_knowledge                   # real module bridge, synthetic snapshot
cp ../.env.example ../.env                                   # set OPENAI_API_KEY, LLM_STRONG, LLM_CHEAP, FIRECRAWL_API_KEY
KNOWLEDGE_BACKEND=fake uv run python -m scripts.run_analysis scripts/example_request.json
```

`KNOWLEDGE_BACKEND=fake` serves the separate `tests/fakes/` agent backend; `real` (default) imports
`bmwow.agent.knowledge_bridge.ontology` and `bmwow.agent.knowledge_bridge.sql_client` (sync or async functions both work).
Configure a `bmwow.knowledge.KnowledgeService` at startup as described in
[the data-layer handoff](../../../docs/data-layer.md). No automatic synthetic fallback or Neon
connection is created. A full agent run still needs LLM/search providers or test overrides;
the inspection script needs neither. `.env` and `data/` live at the repository root.

## Decisions worth knowing

- **Input** is an `AnalysisRequest`: `model_code` (G60, F70, G68) and optional `regions` (EU, CN, US);
  no regions = all regions the model has data for in the registry. Unknown codes/regions and unsupported model–region pairs raise `ResolveError` listing the valid choices,
  in `service.resolve` and already in `service.start_analysis` (before a run is created).
- **Region scoping**: portfolio, competitors and documents are queried with `brief.regions`, sales and
  feedback with `brief.markets`, web searches with the region's `search_locale` (cache key includes it).
  `get_model` / `get_attribute_values` address one model by id and are not region-scoped.
- **Competitors** use curated `sold_regions` on the new bridge. The old no-region fallback applies only
  to legacy unqualified records; each competitor is researched in its requested sale locales.
- **Feedback with several regions**: one finding per theme over all items (weights sum to 1 − noise),
  plus one per theme and region (share of that region's items, citing that region's items only).
- **Brief additions** (optional fields): `region_markets` (region → markets) and `warnings` (shown to the PM).
- **Registry/taxonomy fallbacks**: the bridge returns `None` when an optional contract is unavailable;
  only that signal selects the YAML fallback. Empty results stay empty. Errors from implemented
  functions surface during request resolution or in the agent's failed report.
- **Ontology persistence**: `SituationAnalysis.ontology_persistence` and `RunStatus.ontology_persistence`
  record `skipped`, `stored`, or `failed`; failures include an `error`. The same object appears in the
  streamed `run_finished` event and survives restart through the saved analysis JSON. `done` means
  analysis completion; check this separate outcome for the optional ontology write. The local analysis
  is saved before the hook runs and updated with its outcome. Local save failures still fail the run.
  Older saved analyses without the field load with `None` (unknown), not an assumed write outcome.
  `stored` reports successful completion of the configured hook, not human review or approval.

- **Feedback shares** are relative to the *deduplicated* corpus, so cluster shares + `noise_share` = 1.
  Traced records deduplicate by evidence identity; identical text from distinct original records
  remains distinct. Legacy untraced records retain text/similarity deduplication.
  Clusters that the LLM labels with the same (attribute, polarity) are merged into one finding.
- **`Quantity.origin`** (optional field): `record` (ontology/SQL value, must appear in the cited excerpt),
  `computed` (by code from stored data), `source_text` (must appear in a cited excerpt). Set by code only.
- **Web excerpts**: one `Source` per page (`web:<sha1(canonical_url)[:8]>`). LLM findings carry a verbatim
  `evidence_quote`; verified quotes become the page's excerpt, so excerpts contain what claims rely on.
- **LLM-written claims** may only contain numbers found in the cited excerpts; otherwise the finding is
  dropped (`stats.dropped_unsupported_numbers`).
- Reports list only the sources their findings cite.
- `AttributeValue.as_of` drives `STALE_AFTER_DAYS`; traced records without a date need freshness
  research. Only legacy untraced records retain v1's assumption that an unknown date is fresh.
- Combined/future sales keep their original row citations and temporal labels. They cannot become
  historical model volume, growth, or allocated portfolio shares. Unknown historical coverage
  is reported as partial, even when contextual observations are available.
