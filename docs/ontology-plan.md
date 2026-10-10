# Ontology v0.2 implementation plan

This plan was agreed before implementation after three independent reviews of the
BMW source data, contract validation, and later LangChain integration. The objective
is evidence-backed customer requirements for successor vehicles in three to five
years. The BMW brief prioritizes customer value over detailed engineering specifications.

## Design decisions

Keep the evidence → signal → customer need → requirement → human decision backbone.
Add one business object, `CatalogItem`, for an option or package within a source
edition. Separate an item's identity from a `product_capability` claim about its
availability or performance. Technical capability signals need not have an item.

Use `DESCRIBES` to connect a capability signal to its item, `INCLUDES` for package
membership, `BASELINED_ON` for requirement baselines, and `IS_VARIANT_OF` for an
explicit variant-to-generation relationship. Package conditions encode `requires_all`,
`requires_any`, and `excludes` as typed references; these are constraints to inspect,
not a configuration solver. Keep original text and evidence locators.

Measurements retain `value` for scalars and add `value_range` for genuine intervals.
Exactly one is populated. Separate configuration alternatives into observations:
standard 11 kW and optional 22 kW are two claims, not an 11–22 kW interval. Preserve
test standards, measurement conditions, study questions and response categories.

Add `study_finding` and `commercial_indicator` signals. Without them, the existing
customer study and sales Evidence cannot enter the reasoning chain. Survey means,
response shares, sample counts, and future sales remain distinct.

Requirements record change intent and baseline status. Improve/retain/remove require
an evidenced, applicable BMW capability baseline. Introduce with unknown baseline
remains explicitly uncertain; absence requires an explicit unavailable claim.
Acceptance criteria record a verification method and conditions without inventing
thresholds from complaints. Human review remains an exact-revision event.

Expose typed query, incoming/outgoing traversal, trace, dossier, comparison-readiness,
and proposal functions. Proposal submission creates a candidate closed snapshot and
runs graph validation; it does not mutate the base, authenticate people, or persist.
Authenticated identity, access control, and atomic persistence belong to the service.

## Work allocation and sequence

1. Ontology owner: models, relationships, version, generated contracts and exports.
2. Validation reviewer: graph invariants and regression tests.
3. Agent interface reviewer: deterministic query/proposal contracts and tests.
4. Data reviewer: synthetic source-coverage fixture, source mappings, migration and
   teammate documentation.
5. Integrate, exercise source-informed competency questions, independently review,
   and run all repository Python checks on the final merged snapshot.

No source data is copied into tracked fixtures. No database, scraper, prioritization
formula, full configurator, LangChain orchestrator, or frontend is introduced here.

## Acceptance questions

- What already exists, for which variant, market and catalog date?
- Is the proposal an improvement or an introduction, and why?
- Which original passages and statistics support or challenge it?
- Are comparisons meaningful given units, test standards, study scales and scope?
- Which package prerequisites and future assumptions remain unresolved?
- Can an agent propose a revision without editing evidence or inheriting approval?

## Reference principles

[Palantir design guidance](https://www.palantir.com/docs/foundry/ontology/ontology-best-practices/)
recommends meaningful domain objects, separating identity from observation, curated
properties and validation against business questions. Its
[link model](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview/)
supports traversal in both directions through one relationship. Its
[actions](https://www.palantir.com/docs/foundry/action-types/overview/)
apply validated changes as transactions. BMWow adopts those principles as a portable
Python contract; it is not an implementation of Foundry security or storage.

[LangChain tools](https://docs.langchain.com/oss/python/langchain/tools) and
[structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
accept Pydantic schemas. Inject graph access and actor identity through runtime
context; model schema validation does not replace complete graph validation.

## Implementation and final validation

Implemented as ontology/package v0.2.0 with 12 object types, 15 canonical link
types, six typed agent interfaces, generated input/output contracts, and migration
guidance. Independent reviews tightened announcement versus existing-baseline
semantics, variant consistency, condition-reference retrieval, comparison readiness,
and creation-date anchored launch horizons.

Final checks on 2026-10-10: 155 tests passed; repository Ruff lint and format checks
passed; all three generated contracts were current; the synthetic 57-node/74-link
snapshot validated. A separate ignored local exercise validated representative
records from all eight supplied files (54 nodes/48 links), including a range,
separate charging configurations, package prerequisites, study limitations,
combined future sales, and an unreviewed successor proposal. This is source coverage
and contract verification, not complete ingestion or proof of the proposal's merit.

No BMW originals or derived real-data sample is tracked. The legacy local v0.1
sample remains untouched; migration requires reviewing intent and baselines.
