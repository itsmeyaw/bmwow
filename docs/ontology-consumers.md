# Reading a requirement dossier in ontology v0.2.0

This is the integration guide for the frontend and orchestration owners. The
four product questions are expressible with the current objects and edges. No
new node type, relationship, payload field, or contract version is needed. Python
models and graph validation remain authoritative; this guide explains how to use
their existing distinctions. Private source ingestion and the combined read service
are described in [the ingestion guide](knowledge-ingestion.md) and
[the data-layer handoff](data-layer.md); this dossier example still uses only the
invented fixture.

Run the worked example from `python/`:

```sh
uv run python scripts/inspect_parking_dossier.py
uv run python scripts/inspect_parking_dossier.py --json
```

The second command emits the existing `RequirementDossier` format from
`get_requirement_context`, as defined in `contracts/ontology/agent-contracts.json`.
The first groups its edges for display. That grouping is a consumer example,
not another ontology or API schema. All example content is invented.

## Connecting private knowledge to a dossier

The combined service exposes snapshot graph reads alongside SQL feedback/aspect
projections. `service.snapshot()` returns the graph only; live SQL projections are
not inserted into that GraphBundle. A requirement trace needs materialized original
SourceDocument/Evidence nodes and derived Signals in a closed, validated graph.
Do not use an SQL read ID as a dangling graph reference or treat a SituationAnalysis
finding as an accepted Signal.

Workbook imports already create source-versioned sales/study Evidence. Reviewed
exact study mappings can add Signals; catalog capability claims enter through
reviewed staging bundles. Features, model segments, and source populations need
curation. Operational feedback `EU` membership does not define a sales/study
Europe population. Keep the original context IDs and source locators in dossier views.

Current attribute reads exclude superseded capability Signals, while the full
graph retains them. An exact-revision dossier may legitimately cite an earlier
baseline; preserve that historical identity and make its limitations visible.
Backend requirement persistence, authenticated review events, and frontend wiring
remain separate work from this executable synthetic example.

## What the parking graph actually says

The subject is exact revision `requirement:fixture-parking`, an `improve` proposal
for the successor of `vehicle:bmw-g60` in `market:US`. Its statement asks for
discoverable parking controls and unambiguous status feedback. It does **not**
select a physical switch. Its 0.9 task-success threshold has
`basis=proposed_target`, not an observed result or approved engineering target.

1. **What already exists on the BMW?** Follow outgoing `BASELINED_ON` to
   `signal:fixture-baseline-parking`. Its `product_capability` payload says
   `availability=standard`, with no task-usability measurement. Follow
   `DERIVED_FROM` to `evidence:fixture-catalog-parking`, then `IN_SOURCE` to
   `source:fixture-catalog`; the original locator is PDF page 1. `DESCRIBES`
   connects the claim to `catalog:fixture-parking` in that same edition. This is
   evidence of an offering in the fixture's scope, not evidence that it is easy
   to use or fitted to a particular feedback author's car.
2. **Why does the customer need exist?** Outgoing `ADDRESSES` identifies
   `need:fixture-usability`. Read incoming `SUPPORTS` and `CHALLENGES` on that
   need. Its six supports are `signal:fixture-customer`,
   `signal:fixture-public-positive`, `signal:fixture-competitor`,
   `trend:fixture-controls`, `signal:fixture-study-mean`, and
   `signal:fixture-study-share`. Their edge rationales distinguish reported
   confusion, an implementation preference, a competitor comparison, a forecast,
   and incomplete study statistics. Six links do not mean six independent
   customers, representative demand, or six equally strong reasons.
3. **Why was this proposal made?** Read outgoing `JUSTIFIED_BY` to
   `signal:fixture-customer`, `signal:fixture-competitor`, and
   `trend:fixture-controls`. These are the author's selected reasons for this
   proposal. Keep the competitor-to-BMW and global-to-US `context_transfer`
   explanations visible. The competitor offering is `announced`, so it is a
   claimed future benchmark, not current equipment or a BMW baseline. Follow
   `DEPENDS_ON` to `assumption:fixture-persistence` for the future-relevance
   premise and its validation plan.
4. **What argues against or limits it?** Read incoming `CHALLENGES` on the
   requirement and on reachable needs and assumptions. The fixture's direct
   challenger is `signal:fixture-public-challenge`, whose original opinion
   favours on-screen controls and fewer switches. It limits a possible physical
   implementation suggested by other signals; it does not reject the usability
   outcome. The challenge rationale and review comment now say this explicitly.

`decision:fixture-comment` is a comment on revision 1. Its dossier is
`unreviewed`, with no assigned priority. A comment and a validated proposal do
not establish approval.

`signal:fixture-sales` exists elsewhere in the fixture but has no reasoning edge
into this requirement or need, so it is absent from this dossier. Retrieve it
separately as commercial context if needed. Its combined G60/G68 future volume
does not establish parking-feature demand, and must not be allocated to each
model. The study supports likewise do not establish a representative demand
rate: the mean has unknown scale bounds and both statistics lack sample counts.

## A relationship is a claim with a target

Use the edge's `type`, `source_id`, `target_id`, `rationale`, and
`context_transfer` together. An object type or sentiment label cannot replace
this information.

- `BASELINED_ON`: the proposal's classification of an applicable existing BMW
  offering. It answers what is being introduced, improved, retained, or removed.
  It does not explain customer demand by itself.
- `SUPPORTS`: a Signal or Trend supplies a reason for its specific target
  CustomerNeed, Requirement, or Assumption. Support for a need does not
  automatically select an implementation that might meet that need.
- `JUSTIFIED_BY`: the Requirement author selects a Signal or Trend as a reason
  for that exact proposal. This is not the inverse of `SUPPORTS`; the source,
  target, direction, and rationale express a different assertion.
- `CHALLENGES`: a Signal or Trend opposes or limits its specific target. A
  challenge to an assumption is not automatically rejection of the need; an
  implementation preference is not automatically opposition to customer value.

The customer Signal legitimately both `SUPPORTS` the need and is selected by
`JUSTIFIED_BY` for the proposal. Store and display the object once, with both
edge occurrences. In this case the rationales are respectively “Confusion
motivates an understandable-control outcome” and “Current confusion motivates
the proposal.” Neither edge should be discarded as a duplicate.

Sentiment describes the source interpretation; link rationale describes its
role in an argument. A negative experience can support improvement. A positive
opinion can challenge a different implementation. Do not assign edge direction
or `SUPPORTS`/`CHALLENGES` from sentiment alone.

## Signal kind lookup before creating or rendering a node

`Signal.properties` already uses a Pydantic union discriminated by
`signal_kind`. Some requirements are structural and appear in JSON Schema;
source compatibility, forbidden payloads, and edge rules also require
`validate_bundle`. In particular, nullable base fields do not mean every kind
may populate them. The following profiles describe current validation, rather
than introducing stricter source rules:

- **`customer_feedback`:** every direct original must trace to a
  `feedback_dataset`. Both `public_context` and `capability` are null. Preserve
  reported experience versus opinion or inference in `epistemic_status`.
- **`public_sentiment`:** originals trace to `public_discussion` or
  `editorial_review`. `public_context` is required, including sampling notes;
  `capability` is null. Unknown ownership is not an owner verification.
- **`competitor_capability`:** originals trace to `competitor_official`,
  `product_catalog`, or `editorial_review`. `capability` is required,
  `public_context` is null, `epistemic_status=publisher_claim`, and there must
  be a model reference and a `CONCERNS` Feature. A valid comparison can justify
  a proposal but cannot be its BMW baseline.
- **`product_capability`:** has the same allowed source kinds and required
  capability/model/Feature/publisher-claim profile as `competitor_capability`.
  `BASELINED_ON` adds the stricter BMW-model, shared-Feature, evidence-chain, and
  availability checks below. Kind or source label alone does not establish brand.
- **`study_finding`:** originals trace to `customer_study`; both specialized
  payloads are null. Statistics and survey metadata live on Evidence, not an
  invented Signal measurement. Inspect original question, response category,
  scale, and sample limitations before interpreting feature demand.
- **`commercial_indicator`:** originals trace to `sales_dataset`; both
  specialized payloads are null. Preserve the reported population, combined
  model group, period, and future status on Evidence. It can provide reasoning
  context, but source volume alone does not establish feature demand.
- **`trend_indicator`:** originals trace to `industry_report`,
  `global_indicator`, or `editorial_review`; both specialized payloads are
  null. Distinguish source forecast from observation. A `Trend` synthesizes
  indicators through `DERIVED_FROM`; projected/mixed Trends need assumptions.

All Signals derive directly from Evidence, which has exactly one `IN_SOURCE`.
All direct inputs must satisfy source compatibility. General `SUPPORTS`,
`CHALLENGES`, and `JUSTIFIED_BY` endpoint rules do not whitelist kinds as
“proven demand”; the edge rationale and source limitations remain substantive
review. Most kinds' epistemic status is not fixed by validation; both capability
kinds specifically require `publisher_claim`.

Only the two capability kinds may use `DESCRIBES`, at most once per Signal. The
Signal's original source-document set must equal the CatalogItem's one original
edition. Availability and measurements belong to the Signal's capability;
offering code/identity and package membership belong to CatalogItem. A capability
need not have a CatalogItem. `INCLUDES` is membership, not an availability claim.

For `BASELINED_ON`, the target must be a `product_capability` Signal with a
traceable original, a shared Feature, and the requirement's BMW model or an
explicit variant of it. Market/model/country/engine differences need
`context_transfer`; that text is an explanation, not proof of applicability.
`known_present` accepts standard, optional, or available-unspecified claims;
`known_absent` requires an explicit unavailable claim. Announced or missing
equipment does not prove current presence or absence. Improve/retain/remove
require `known_present`; unknown introduction remains a premise to validate.

## Frontend recipe

1. Request `get_requirement_context` with the **exact revision ID**. Build
   `nodesById` from `dossier.trace.nodes` and `edgesById` from
   `dossier.trace.edges`. Use the same IDs for rendering, source expansion, and
   decisions; `entity_key` is history identity, not a substitute revision ID.
2. Group direct outgoing `BASELINED_ON`, `ADDRESSES`, and `JUSTIFIED_BY` edges as
   shown in `question_edges` in the executable example. For each addressed need,
   group incoming support and challenges by target. Keep direct incoming
   `SUPPORTS` on a Requirement distinct from its selected justifications.
3. Display challenges to the proposal, its needs, and its assumptions with the
   exact challenged target and rationale. Put premise status, impact-if-false,
   and validation plans alongside those sections. Do not flatten all opposition
   into a generic negative-sentiment list.
4. Reuse one Signal detail view with multiple relationship badges/occurrences.
   Use edge ID as the occurrence key within a section, and node ID as the shared
   object key. Deduplicate original Evidence by ID/dedup identity for record
   counts; preserve every reasoning path. Source independence groups are a
   separate question, and missing groups or unknown authors are not proof of
   independence. Study cells and forecasts are not individual customer records.
5. A baseline detail shows capability availability/conditions, scope, original
   locator, catalog edition, epistemic status, and remaining limitations. Keep
   criteria basis/test conditions, uncertainty, and `prioritization_rationale`
   visible. Do not turn confidence or number of links into importance or priority.
6. Expand originals through stored `DERIVED_FROM` and `IN_SOURCE` paths.
   `trace.references` are property references such as criterion Evidence IDs,
   model/market IDs, or package conditions; label them separately from stored
   edges. Do not invent ABOUT, SUPPORTS, or other edges from these references.
7. If either truncation flag is true, show incomplete context and fetch missing
   branches. A missing result is not evidence of no challenges or no baseline.
   Increase bounds or use targeted `trace_evidence`/`traverse`/paged queries as
   needed. Even a complete selected trace is not a search for every unlinked
   Signal about the Feature; broader research requires separate queries.
8. Render `dossier.review` from exact-revision Decision events. Keep comments
   distinct from approvals, human priority distinct from suggested rationale,
   and equal-time conflicting reviews visible as ambiguous.

## Orchestration recipe and write boundary

Validate the closed input snapshot. Retrieve scoped candidate Signals and needs,
inspect originals and opposing evidence, then obtain the exact requirement
dossier. Record which statements support the need, which justify the proposal,
which establish the baseline, and which limit it. A scoped query is discovery;
the proposed links and their rationales express the selected reasoning.

The proposal tool accepts one software-authored Requirement plus links to
**existing** nodes. Its directions are:

- Outgoing from the new Requirement: `CONCERNS`, `ADDRESSES`, `JUSTIFIED_BY`,
  `BASELINED_ON`, `DEPENDS_ON`, and `SUPERSEDES`.
- Incoming to the new Requirement: `SUPPORTS` and `CHALLENGES` from existing
  Signals or Trends. They do not allow edits to an existing need or assumption.

New Evidence, Signals, Needs, Trends, Assumptions, and CatalogItems require the
separate ingestion/synthesis path. Adding them as extra proposal properties or
dangling targets is rejected. The proposal cannot create a Decision or claim a
human-set target. Check the service-bound actor and snapshot precondition, run
`validate_proposal` on the complete merged candidate, and persist atomically in
the service. `accepted=true` means structural/graph acceptance, not truth,
product merit, persistence, or human approval.

The implemented `FileCandidateStore` accepts local non-Requirement candidates
after merged validation and a fingerprint check. It rejects Requirement/Decision
nodes and relationships touching existing Requirements/Decisions, so it cannot
persist the RequirementProposal result. That proposal needs its own service write
operation; the current analysis `store_findings` hook is still unconnected.

A revision is a new Requirement ID with the same entity key, next consecutive
revision, and `SUPERSEDES` to the latest revision. Re-evaluate which baseline,
justification, and challenge links still apply; attach new edge IDs to the new
revision. Requirement-level incoming challenges are not automatically copied.
Challenges on a reused need or assumption remain reachable. Previous review and
priority events stay on the old revision; the new revision starts unreviewed.

## Distinctions considered and rejected

- **Seven separate Signal node types:** rejected for this task. Kind already
  discriminates payloads and provenance rules; splitting the wire types adds
  migration work without improving these four answers. Render kind-specific
  details and validate the graph instead. Kind, epistemic status, and argument
  role are separate dimensions.
- **A new Capability object:** rejected for this task. Capability already holds
  scoped availability/performance, while CatalogItem supplies edition identity.
  The baseline is a sourced claim, not a timeless Feature or catalog code.
- **Collapse SUPPORTS and JUSTIFIED_BY, or store their inverses:** rejected.
  Support for a need and selected justification for a proposal can reuse the
  same Signal while asserting different things. Keep canonical direction,
  target, rationale, and both occurrences.
- **A DemandEvidence type or automatic demand/priority edge:** rejected. A
  source category or a validated edge cannot establish representativeness,
  customer value, causality, or a suitable threshold. Original measurements,
  synthesis uncertainty, and human review do that work.
- **A new Solution/Alternative node for the physical-versus-screen debate:**
  deferred. This Requirement specifies a customer outcome and leaves the
  implementation open. Its challenge rationale can express a conditional
  implementation limitation. Concrete customer-facing alternatives can be
  separate Requirements with separate entity keys that address the same need;
  neither is a revision of the other. v0.2 does not encode exclusive choice
  groups, a selected implementation, or machine-addressable subclaims/criteria
  targeted by challenges. Add such structure only when that product workflow
  actually requires it; do not infer it from this fixture.
- **Automatically inherit review or opposition on revision:** rejected. Approval
  and priority are exact-revision human events; implementation-specific opposition
  must be reconsidered for the new proposal. Keep old events and evidence visible.

The remaining limitation is semantic review: validation checks permitted types,
paths, scope explanations, availability, and revision rules. It cannot decide
whether a rationale really supports its stated target. The fixture clarification
fixes an ambiguous argument, rather than changing those rules or adding a type.
The invented baseline excerpt now explicitly states standard equipment, matching
its capability claim; previously the excerpt only identified the offering/code.
These are corrections to synthetic demonstration text, not edits to real source
Evidence or historical Decision events. Such records remain immutable in the app.

See [ontology guide](ontology.md) for full meanings and
[consumer acceptance tests](../python/tests/ontology/test_consumer_questions.py) for the
four-question trace, occurrence preservation, and partial-result behavior.
