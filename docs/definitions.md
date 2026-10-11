# Definitions across ontology, knowledge, and orchestration

The layers share vocabulary and source qualifications, but serve different jobs.
Use the Python definitions below instead of copying schema declarations from the
original orchestration spec. The ontology version remains **0.2.0**; wire field
names and generated contracts remain stable.

## Definition ownership

- `python/bmwow/ontology/models.py` owns persisted objects, Context, Locator,
  Measurement, NumericRange, and the availability, epistemic-status, sentiment,
  and confidence vocabularies. `relationships.py` and `validation.py` own link
  and complete-graph rules. The three generated JSON contracts come from these
  modules and `ontology/tools.py`.
- `python/bmwow/knowledge/records.py` owns read projections: ModelNode,
  AttributeValue, FeedbackItem/Aspect/Classification, SalesRow, StudyScore,
  DocChunk, and retrieval metadata. These import ontology qualifications.
  `agent/models/knowledge.py` only re-exports the same classes for compatibility.
- `python/bmwow/knowledge/types.py` owns shared research-locale fields and mapping
  status. Curation uses the strict SearchLocale subclass in `knowledge/config.py`;
  analysis uses the shared permissive DTO. Their fields have one definition,
  while their existing unknown-field validation policies stay distinct.
- `python/bmwow/agent/models/evidence.py` owns analysis-only Source, Quantity,
  Finding, ProductBrief, AgentReport, SituationAnalysis, and the v2 evidence
  packages and assessments. It imports shared knowledge definitions and ontology
  vocabulary. Polarity, Direction, TrendHorizon and AvailabilityStatus are shared
  within orchestration from this module; the old `nodes/common.py` Polarity import
  remains compatible.

## Similar names with different meanings

**Source and SourceDocument.** An analysis Source is a citation envelope containing
an excerpt and original read metadata. A SourceDocument identifies an original
document or dataset version in the graph. Source.kind identifies how analysis
retrieved the record (`ontology`, `sql`, `web`, `feedback`), rather than the
SourceDocument's source_kind. A `kg:` or `fb:` wrapper is a read citation, not a
new graph identity. Preserve the original EvidenceReference and Locator when
later accepting a graph candidate.

**Finding and Signal.** A Finding is an analysis interpretation with report-local
IDs, an attribute key, a claim and cited Sources. A persisted Signal requires a
signal kind, original context, epistemic status, extraction-confidence reason,
provenance, and validated evidence links. A Finding is not a complete Signal
payload. Analysis completion and the optional persistence hook's success do not
establish graph acceptance or human approval. Candidate translation remains a
separate integration step.

**Polarity and sentiment.** Finding.polarity includes `demand`, meaning customers
want something. Signal.sentiment describes sentiment and also permits mixed,
unknown and not-applicable observations; it has no `demand` value. Imported
FeedbackAspect.sentiment uses the preprocessing values Positive/Negative/Neutral.
Feature Request is Neutral under the preprocessing policy. Preserve request
intent in the interpreted statement/CustomerNeed; do not cast demand into graph
sentiment or infer negative sentiment from a request alone.

**Direction and polarity.** The v2 feedback analysis uses problem/request/strength/
neutral Direction to describe the customer's intent. It maps those values to
negative/demand/positive/neutral Polarity for the existing Finding contract.
Direction does not replace the imported aspect's sentiment. TrendHorizon is the
analysis's now/1-2y/3y+ bucket; it does not supply the graph's scoped forecast dates,
assumptions or uncertainty.

**Confidence and priority.** Analysis Confidence uses the ontology's assessed
low/medium/high labels. Finding.confidence and FeatureAssessment.certainty use
these labels for an analysis claim or judgment; they do not establish extraction
confidence. Ontology ConfidenceLevel additionally permits unassessed. The graph's
extraction-confidence reason and uncertainty limitations still need to be supplied;
an assessed analysis label cannot supply them.
Feedback intensity, signed Sentiment Score, occurrence share, extraction
confidence, uncertainty and requirement priority remain different quantities.
An unassessed graph value must not silently become low confidence in analysis.

**Availability and CapabilityAvailability.** AgentReport.availability records whether
a data source was usable in the run: ok/partial/unavailable. CapabilityAvailability
describes the evidenced offering: standard/optional/announced and the other ontology
states. An unavailable dataset does not prove that a vehicle lacks a capability.

**Evidence packages and graph objects.** The v2 EvidencePackage assembles report-local
facts, comparisons, CustomerSignals, TrendSignals, quotes and coverage for one feature.
Despite their names, CustomerSignal and TrendSignal are analysis summaries referencing
Finding IDs, not persisted ontology Signals. FeatureAssessment is a guarded agent
judgment, not a Requirement or authenticated human Decision. Its importance ranking
and assessment do not assign requirement priority or approval. The graph conversion
and requirement/review write paths remain separate integration work.

**Quantity and Measurement.** Quantity is the analysis summary of a number and
its origin. Measurement retains original statistic, units, interval, period,
sample/denominator, scale, population and conditions. Read records and Sources
retain that full Measurement; summarizing a number does not replace it or permit
inventing missing metadata.

**Sales status.** Ontology Measurement.temporal_status uses `historical`; the
legacy SalesRow.status calls that same observed state `actual`. The projection
converts it explicitly. Source-reported future, forecast and unknown states retain
their original labels. This compatibility translation does not establish a
future observation as an actual sale.

**ModelNode and VehicleModel.** ModelNode is a read projection with curated
segment/powertrain metadata and dataset coverage. VehicleModel is stable graph
identity. ModelNode.regions describes data coverage; sold_regions is a separate
curated availability policy. Neither feedback coverage nor marketing-name
similarity establishes variant identity or sale availability.

**Region and market.** Analysis regions choose registry groups and research
locales. ProductBrief.markets contains feedback query selectors. Original
sales/study regions remain source-specific: a source-reported Europe population
with unknown countries is not defined by feedback's EU member-country grouping.
Retrieve that source context explicitly rather than assigning invented countries
to make the query match. SearchLocale is research policy, not source scope.

**Aspect Term/Label and VFC Category/Issue Type.** FeedbackClassification retains
legacy wire fields `vfc_category` and `vfc_issue`, but these mean the original
Aspect Term and Aspect Label. Its `aspect_term` and `aspect_label` Python
properties express that meaning without adding serialized fields. In contrast,
FeedbackAspect.vfc_category and issue_type are coarse buckets. Original labels,
coarse buckets, ontology Feature IDs and analysis attribute keys are distinct;
only an exact reviewed mapping establishes their association. `CONTEXT.md` owns
the preprocessing glossary.

The v2 feedback agent also uses interim aliases from `agent/rules.yaml`, restricted
to the active taxonomy, when a reviewed classification attribute is absent. Those
analysis guesses do not create reviewed Feature mappings in the knowledge layer.

Ontology Feature.domain, coarse VFC categories and the fallback analysis
taxonomy's areas are different groupings. For example, the fallback area's
`Digital_UX` spelling is not an ontology Domain value. A configured Feature key
and its reviewed mapping establish identity; a similar area or bucket name does
not. Preserve these distinct taxonomies instead of merging their labels.

## Validation at the boundary

Read AttributeValue and analysis Source use the canonical CapabilityAvailability
and EpistemicStatus vocabularies. Optional unknown metadata remains null; arbitrary
strings are rejected rather than becoming apparently valid ontology qualifications.
MappingStatus has one definition for proposed/reviewed mappings. Proposal review
does not mean the underlying source statement or requirement has human approval.

The graph's strict complete-snapshot validation remains authoritative. Read DTOs
retain their existing permissive extra-field policy, and curation configuration
retains its strict extra-field policy. Validate any accepted candidate against the
complete merged graph; authentic human Decisions require their separate write path.

Tests in `python/tests/knowledge/test_definition_boundaries.py` cover vocabulary
alignment, locale policies, request-versus-sentiment distinctions, and legacy VFC
wire semantics. `bmwow-schema --check` verifies that consolidation does not change
the generated ontology contracts.
