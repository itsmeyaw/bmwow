# `bmwow/agent/` — situation analysis agents

Implements [SPEC.md](SPEC.md), extended as described under *Pipeline v2* below. Four agents run in
parallel; `structure_agent` turns their validated reports into one evidence package per feature and a
guarded judgment, and the `SituationAnalysis` (schemas in `bmwow/agent/models/evidence.py`) goes to
`candidate_agent`.

## Pipeline v2

```
resolve ─▶ [baseline ∥ competition ∥ feedback ∥ trends] ─▶ validate ─▶ structure_agent ⇄ gap_fill ─▶ collect
```

Division of labor: the knowledge adapter fetches, **code computes every number**, the LLM only reads
unstructured text (web pages, vague feedback texts) and judges with a rubric, and code guards the
judgment. Missing data is reported per source in `AgentReport.availability`, never hidden.

| Node | Input | Method | Output |
|---|---|---|---|
| resolve | model code, optional regions | registry + ontology lookups | `ProductBrief` |
| baseline | brief; catalog, sales, studies | code only: catalog values (standard/optional), sales per region (forecast/group labels kept), study scores per question | facts + availability |
| competition | brief; core features (`rules.yaml`) | code writes queries per competitor × feature in the region locale → Firecrawl → LLM extracts value + verbatim quote per page → code checks quote, number and competitor | competitor values with test standard |
| feedback | brief; feedback items with aspects | code counts distinct items per feature × direction × region against the relevant population (e.g. range: BEV+PHEV), Wilson CI, thin flag, region test; sub-themes from aspect terms, LLM groups texts only for generic-only features; candidate features from unclassified topics | findings with `stats`, `sub_themes`, `candidates` |
| trends | brief; stored studies + web | LLM tool loop; code counts independent sources (thin when 1) | trends with horizon, direction |
| validate | 4 reports | citation and number checks, missing reports filled | validated reports |
| structure_agent | validated reports | assemble packages (code) → rubric judgment (LLM, cites package ids) → guard (code), one revision then flagged | `evidence_packages`, `feature_assessments` |
| gap_fill | important features without competitor evidence | one targeted competition round, merged into the competition report | more competitor evidence |
| collect | everything | build + persist the hand-off, optional `store_findings` | `SituationAnalysis` |

**BMW data and LLMs.** Steps that would send BMW data to an LLM (feedback sub-themes from texts, the
structure_agent judgment) run only with `ALLOW_LLM_ON_INTERNAL_DATA=true`. With the default `false`,
they are skipped and reported (`availability`, `FeatureAssessment.note`); everything computed by code
still runs. Tests enable it against synthetic data only.

**Ontology integration.** Feature keys come from the knowledge layer's taxonomy (`get_taxonomy`);
feedback uses `FeedbackClassification.attribute` (curated VFC mapping) before the interim aliases in
`rules.yaml`, which only produce features of the active taxonomy. Competitor values are compared only
within the same unit, test standard (ontology `Measurement.test_standard` when present) and region.
Study scores cite their ontology Evidence nodes. `tests/knowledge/test_pipeline_ontology.py` runs the
whole pipeline on the synthetic ontology snapshot.

**Tuning** lives in `rules.yaml`: thin thresholds, denominators, interim aliases, generic terms, core
competitor features, guard thresholds, judgment and gap-fill budgets. Competition shares
`MAX_TOOL_CALLS_PER_AGENT` across competitors × features; raise it for real runs.

[Definition boundaries](../../../docs/definitions.md) identifies the owner of each
shared type and explains why Finding/Signal, Source/SourceDocument, demand/sentiment,
and feedback/source-region selectors remain distinct. Knowledge records are
compatibility re-exports, and availability/confidence vocabulary comes from the
ontology. The original SPEC links to these owners instead of repeating schemas
or fallback configuration.

```
service.py        list_models / resolve / start_analysis / get_analysis / stream_analysis / explain / aclose
                  ← the API layer calls these
supervisor.py     graph: START → resolve_request → 4 agents (one superstep) → validate → structure_agent
                  ⇄ gap_fill → collect → END; a resolve error goes straight to END; build_subgraph()
structure.py      evidence packages per feature (assemble) and the guard for judgments
stats.py          Wilson interval, two-proportion test, distributions (plain math, portable)
rules.py, rules.yaml  thresholds, denominators, interim aliases, budgets (all judgment knobs)
resolve.py        AnalysisRequest (model code + optional regions) → ProductBrief; deterministic, no LLM
registry.py       model registry + region list (knowledge layer if it offers them, else models.yaml /
                  regions.yaml); fail-fast request checks
nodes/            baseline, competition (Send fan-out per competitor), feedback, trends, structure (judge);
                  common.py = context, availability, failure isolation, bounded tool loop
validation.py     citation + quantity + claim-number checks (drop and count, never repair)
router.py         data need → sql_rag | graph_rag | web_search (one-line source swaps)
tools/knowledge.py  coupling to bmwow/agent/knowledge_bridge (thin bridge to bmwow.knowledge); swap storage behind it
tools/web_search.py Firecrawl behind SearchBackend, on-disk cache, OFFLINE_MODE
tools/feedback_stats.py  feedback dedupe by evidence identity (portable, no clustering)
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

For private snapshot plus SQL feedback, use `create_knowledge_service(...)` to
construct `CombinedKnowledgeService`, then inject it through the same bridge.
The factory needs a feedback connection and explicit curation; it does not import
source workbooks or activate a fallback backend on its own. Follow
[the ingestion guide](../../../docs/knowledge-ingestion.md) for workbook import and
aggregate inspection. After preparing the private snapshot and matching config,
the existing analysis CLI can resolve a brief without providers:

```sh
# From python/; .env contains DATABASE_URL for this check.
PYTHON_DOTENV_DISABLED=1 uv run python -m scripts.run_analysis scripts/example_request.json \
  --snapshot ../data/knowledge/snapshot.json \
  --knowledge-config ../data/knowledge/snapshot.config.json \
  --env-file ../.env --resolve-only
```

## Decisions worth knowing

- **Input** is an `AnalysisRequest`: `model_code` (G60, F70, G68) and optional `regions` (EU, CN, US);
  no regions = all regions the model has data for in the registry. Unknown codes/regions and unsupported model–region pairs raise `ResolveError` listing the valid choices,
  in `service.resolve` and already in `service.start_analysis` (before a run is created).
- **Region scoping**: portfolio, competitors and documents are queried with `brief.regions`, sales and
  feedback with `brief.markets`, web searches with the region's `search_locale` (cache key includes it).
  `get_model` / `get_attribute_values` address one model by id and are not region-scoped.
- **Source-region context**: source Europe sales/study populations stay distinct
  from feedback EU membership. The combined read service can retrieve their original
  regional observations explicitly; when the baseline's sales call uses feedback
  country selectors, it cannot select source EU totals with unknown membership. Connecting
  that sales context into analysis remains orchestration work. Typed study scores
  are already read by the baseline and retain their original measurement metadata.
- **Curation and current capabilities**: the private template leaves segments and
  Feature mappings for review. Only exact reviewed mappings attach Feature keys;
  original SQL aspect labels remain intact. Attribute reads exclude superseded
  Signals, while citation resolution and full snapshots preserve their history.
- **Competitors** use curated `sold_regions` on the new bridge. The old no-region fallback applies only
  to legacy unqualified records; each competitor is researched in its requested sale locales.
- **Feedback with several regions**: one finding per feature, direction and region (share of that
  region's relevant items, citing that region's items only), plus one over all requested regions;
  each region is tested against the others combined.
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
  The current read services have no `store_findings` implementation. The separate
  `FileCandidateStore` validates and atomically accepts non-Requirement candidates;
  translating analysis outputs and wiring the optional hook remain pending.
  Requirements, Decisions, and relationships touching them need separate write paths.

- **Feedback shares** count distinct deduplicated items, never aspect rows; one item can count for
  several features. Traced records deduplicate by evidence identity; identical text from distinct
  original records remains distinct. Legacy untraced records retain normalized-text deduplication.
- **`Quantity.origin`** (optional field): `record` (ontology/SQL value, must appear in the cited excerpt),
  `computed` (by code from stored data), `source_text` (must appear in a cited excerpt). Set by code only.
- **Web excerpts**: one `Source` per page (`web:<sha1(canonical_url)[:8]>`). LLM findings carry a verbatim
  `evidence_quote`; verified quotes become the page's excerpt, so excerpts contain what claims rely on.
- **LLM-written claims** may only contain numbers found in the cited excerpts; otherwise the finding is
  dropped (`stats.dropped_unsupported_numbers`). Feedback and baseline claims come from templates.
- Reports list only the sources their findings, sub-themes and candidates cite.
- `AttributeValue.as_of` drives `STALE_AFTER_DAYS`; traced records without a date need freshness
  research. Only legacy untraced records retain v1's assumption that an unknown date is fresh.
- Combined/future sales keep their original row citations and temporal labels. They cannot become
  historical model volume, growth, or allocated portfolio shares. Unknown historical coverage
  is reported as partial, even when contextual observations are available.
