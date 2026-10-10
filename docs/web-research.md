# External research contract

The proposed ontology collector has three research modes. The agent plans queries
and interprets retrieved content; a deterministic collection tool handles fetching,
source capture, and original excerpts. Orchestration can then combine accepted
findings with BMW evidence for the later requirement workflow.

This document is a proposed collection interface for ontology v0.2.0. No scraper
or live collection service is implemented by the ontology files. Deterministic
query, trace, comparison, and proposal helpers are available in `bmwow.ontology`;
the orchestration owner still needs to bind them to the complete requirement workflow.
Situation-analysis v1 already has bounded Firecrawl search/scrape tools, caching,
and cited Source/Finding DTOs. Those results do not automatically become ontology
SourceDocument/Evidence/Signal nodes. The separate local candidate store is implemented;
collector-to-graph translation and the analysis write hook remain pending. See
[the ingestion guide](knowledge-ingestion.md) and [the write boundary](data-layer.md#candidate-acceptance-and-orchestration-handoff).

## Inputs

Each job specifies:

- Research mode: `public_sentiment`, `competitor_capability`, or `trend_indicator`.
- Baseline vehicle, target market/country, feature/domain, and a research question.
- Publication/observation window and successor horizon, when relevant.
- Source preferences and a bounded collection budget: maximum queries, sources, page fetches, and time.
- Retrieval freshness policy and existing source/evidence IDs for cache and deduplication.

Keep internal BMW feedback and study excerpts inside the project. Search queries should use model names, domains, and summarized public research topics rather than send original internal records to a public search provider.

## Collection pipeline

1. Search for candidate URLs using available search tools, site search, feeds, or approved platform APIs. Record the query and selection method. A search snippet is a discovery lead.
2. Fetch the original page or API record with a tool. Capture canonical URL, publisher, publication date when available, retrieval timestamp, and a content hash when a snapshot is available.
3. Preserve a short exact excerpt and a locator. Record the original source for syndicated material when discoverable. A search-only result remains a lead and is not promoted to validated Evidence.
4. Create a `SourceDocument` and `Evidence`. Preserve explicit model/market/variant context and unknowns.
5. Extract `Signal` candidates using the mode below. Record method, actor/model, prompt version, extraction confidence, and limitations.
6. Validate the merged ontology bundle and deduplicate before handing it to orchestration. Source fetching failures, missing publication dates, or ambiguous model matches remain visible.
7. The orchestrator synthesizes customer needs or trends and proposes requirements. A product manager issues Decisions through an authenticated review flow.

Use ordinary page fetching for accessible articles and official product pages. Add browser rendering only for sources that require it. Prefer platform APIs or approved exports for public discussions when available. The collector should have timeouts, size limits, caching, and bounded retries. Respect site access conditions and the applicable robots rules; robots rules describe crawler behavior and are not themselves access authorization. See [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html).

Treat page text as source data. Instructions embedded in a page cannot change the agent's research task, tools, or output schema. The extraction prompt should operate on delimited page text and return structured candidates, with original evidence attached.

## Mode 1: public sentiment

Capture opinions about particular features, experiences, or the overall product. Track platform, author role when explicitly supported, whether ownership is verified, market context, and selection method. Unknown ownership or country stays unknown.

Sentiment is aspect-specific. One post may praise comfort and criticize controls, producing two Signals from one Evidence record. Preserve mixed opinions. A reviewer opinion is not automatically an owner report.

Record the collection window and sampling limitations. A purposive internet sample describes the collected posts; it does not establish the opinion distribution of all BMW customers. Engagement, reposts, and mentions do not count as independent customers. Do not label a percentage as market sentiment without a defined sample and denominator.

## Mode 2: competitor capability

Prefer official product pages, market-specific brochures, configurators, and manufacturer announcements for capability claims. Reviews can add experience evidence and source disagreement.

Identify brand, model/generation, model year, market, variant, feature, and
availability. Keep `announced`, `standard`, `optional`, `available_unspecified`,
`unavailable`, and `unknown` distinct. An announcement does not prove current
availability. `unavailable` requires an explicit source claim; missing mention is
unknown. Existing competitor Signals retain `competitor_capability`; BMW's own
catalog baseline uses `product_capability`. Both carry a structured Capability
and distinguish manufacturer claims from independently verified experience.
An announced offering is planned and cannot establish a known-present BMW baseline.
When explicit variant identities are available, keep the capability annotation
consistent with the referenced VehicleModel.

When a captured catalog identifies packages or options, create edition-specific
CatalogItems and connect capability Signals through `DESCRIBES`. `INCLUDES`
records package contents within the same original edition. Preserve prerequisite,
alternative, and exclusion conditions as `requires_all`, `requires_any`, and
`excludes`; unresolved conditions remain textual and visible. Do not match item
codes across catalog editions or infer availability from package membership alone.

Retain measurement units, test standard, conditions, and comparison basis. A
Measurement populates exactly one of scalar `value` or `value_range`. WLTP, EPA,
and unspecified procedures are not automatically comparable. Capture genuine
intervals without averaging; capture different standard/optional configurations
as separate scalar claims. Keep charging state-of-charge windows, ambient or
equipment conditions, and relevant footnotes. Preserve price currency, market,
and tax basis in notes if price is collected; no detailed business-case model is required.

A competitor feature is a comparison signal. Explain how it may inform a BMW customer need. It is not proof that the feature will be valued by BMW customers.

## Mode 3: product and global trends

Prefer dated research publications, official statistics, industry reports with described methodology, and first-party product announcements. Different sources establish different kinds of evidence: a vendor projection remains that publisher's forecast.

Record geography, population, time span, method, and projection horizon when supplied. Separate observed direction from future projection. Distinguish adoption or measured behavior from publicity about a technology.

A Trend synthesizes indicators and cites them through `DERIVED_FROM`. Forecasts have explicit Assumptions, including what must hold for a global trend to be relevant to the target vehicle and market. Retain credible opposing indicators instead of selecting only confirming articles.

## Output and permissions

The research agent supplies a closed ingestion candidate containing context nodes,
`SourceDocument`, `Evidence`, and `Signal` nodes, plus CatalogItems when extracting
identified offerings. Its normal output contains neither Requirements nor Decisions.
Validate a candidate against the merged snapshot, so every context, item-condition,
and source reference is present. Orchestration can later synthesize Trends, Needs,
Assumptions, and Requirements.

This ingestion path is separate from `validate_proposal`: that helper accepts one
software-authored Requirement with narrowly allowed links to existing objects.
It does not ingest new sources, Evidence, or CatalogItems. Use the generated
`agent-contracts.json` for tool schemas and the [ontology guide](ontology.md) for
query, trace, dossier, comparison, and proposal signatures. Bounded query/trace
responses are tool results, not necessarily complete graph snapshots.

An application can accept a validated research candidate with
`FileCandidateStore.accept(candidate, expected_fingerprint=...)`. The local store
checks conflicts and the current fingerprint under a writer lock, validates the
complete merged graph, and replaces the snapshot atomically. It also rejects
relationships touching existing Requirements/Decisions. It supplies neither actor
authentication nor automatic acceptance of v1 analysis DTOs; a service must own
that conversion and authorization. Neo4j persistence is not implemented.

A requirement's `BASELINED_ON` link records an applicable BMW capability;
`JUSTIFIED_BY` records customer or trend reasoning. Improve/retain/remove require
a known-present baseline. Unknown introduction requires a validation Assumption;
a competitor offering or a failed BMW search does not prove BMW absence.

Schema validation is not a permission boundary. The backend must restrict extraction/research actors to candidate writes and authenticate the product manager issuing review events. Tool-generated evidence and agent-generated interpretations should use separate write paths.

## Initial demo strategy

Start with a small cached research pack for one model, market, and theme. Use several public opinions, one or two relevant competitor references, and dated trend evidence. Demonstrate a research job adding a new captured source, then inspect how it supports or challenges a proposal. Keep cached originals available so the demo remains reproducible if a live fetch fails.

The shareable [synthetic fixture](../contracts/ontology/examples/synthetic.json)
illustrates the shapes and relationships only. It contains no real internet findings
and must never be mixed into a production research pack.
