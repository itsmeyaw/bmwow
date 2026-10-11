-- Idempotent: python/scripts/export_analysis.py applies this before it writes a run.
-- Stored results of the situation-analysis pipeline (input -> four agents -> structure_agent ->
-- candidate_agent). One run = one model and its regions. Every table is keyed by run_id; a re-export
-- of the same run replaces its rows. Comments describe each column for SQL readers, including LLMs.

CREATE TABLE IF NOT EXISTS analysis_runs (
  run_id        TEXT PRIMARY KEY,
  model_code    TEXT NOT NULL,
  model_name    TEXT,
  segment       TEXT,
  regions       TEXT[] NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL,
  exported_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  llm_model     TEXT,
  code_version  TEXT,
  inputs        JSONB NOT NULL DEFAULT '{}'::jsonb,
  agent_status  JSONB NOT NULL DEFAULT '{}'::jsonb,
  notes         TEXT[] NOT NULL DEFAULT '{}'
);
COMMENT ON TABLE analysis_runs IS 'One pipeline run: the analysed BMW model (e.g. G60) in the requested regions (EU, US, CN).';
COMMENT ON COLUMN analysis_runs.model_code IS 'BMW model code analysed, e.g. G60 (BMW 5 Series Sedan).';
COMMENT ON COLUMN analysis_runs.regions IS 'Regions the run covers; findings with region NULL apply to all of them.';
COMMENT ON COLUMN analysis_runs.inputs IS 'Fingerprints of the inputs (knowledge snapshot, web corpus, feedback counts) and rule versions.';
COMMENT ON COLUMN analysis_runs.agent_status IS 'Per agent: ok / partial / failed, with the reasons a data source was unavailable.';
COMMENT ON COLUMN analysis_runs.notes IS 'Run-level caveats (e.g. data that was missing).';

CREATE TABLE IF NOT EXISTS analysis_features (
  run_id            TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  attribute         TEXT NOT NULL,
  label             TEXT NOT NULL,
  area              TEXT NOT NULL,
  rank              INTEGER NOT NULL,
  importance        DOUBLE PRECISION NOT NULL,
  assessment        TEXT NOT NULL,
  method            TEXT NOT NULL,
  certainty         TEXT,
  widespread        TEXT,
  what_exactly      TEXT,
  reasoning         TEXT,
  rule_suggestion   TEXT,
  guard_status      TEXT,
  brand_or_safety_relevant BOOLEAN,
  facts             TEXT[] NOT NULL DEFAULT '{}',
  coverage          TEXT[] NOT NULL DEFAULT '{}',
  is_mapped         BOOLEAN NOT NULL,
  cited_ids         TEXT[] NOT NULL DEFAULT '{}',
  guard             JSONB NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY (run_id, attribute)
);
ALTER TABLE analysis_features ADD COLUMN IF NOT EXISTS cited_ids TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE analysis_features ADD COLUMN IF NOT EXISTS guard JSONB NOT NULL DEFAULT '[]'::jsonb;
COMMENT ON COLUMN analysis_features.cited_ids IS 'Ids the reasoning relies on: analysis_findings.finding_id or analysis_sources.source_id (fb:… = a customer feedback item).';
COMMENT ON COLUMN analysis_features.guard IS 'Code checks of the LLM judgment that failed (rule, detail); empty when all passed.';
COMMENT ON TABLE analysis_features IS 'One row per product feature in a run: the evidence summary and the assessment of the feature for the successor model.';
COMMENT ON COLUMN analysis_features.attribute IS 'Feature key, e.g. fast_charging; "unmapped:<area>" for feedback areas without a feature mapping.';
COMMENT ON COLUMN analysis_features.area IS 'Feature group: Exterior, Interior, Powertrain, Digital_UX, Driver_assistance, Business, or unmapped.';
COMMENT ON COLUMN analysis_features.rank IS 'Importance rank (1 = most important), by the largest customer problem/request share (95% CI lower bound).';
COMMENT ON COLUMN analysis_features.importance IS 'Largest 95% CI lower bound of a customer problem or request share (0-1).';
COMMENT ON COLUMN analysis_features.assessment IS 'gap = we fall short of customers or competitors; strength = we lead or customers praise it; hygiene_factor = customers complain but competitors are no better (a baseline expectation); demand = customers or the market ask for more; unclear = evidence too thin.';
COMMENT ON COLUMN analysis_features.method IS 'judge = LLM judgment with a rubric, checked by code rules; rule = computed by code from the shares and comparisons only (low certainty).';
COMMENT ON COLUMN analysis_features.what_exactly IS 'The concrete customer issue or wish, e.g. a sub-theme.';
COMMENT ON COLUMN analysis_features.reasoning IS 'Reasoning of the assessment; ids in brackets refer to analysis_findings.finding_id or analysis_sources.source_id.';
COMMENT ON COLUMN analysis_features.guard_status IS 'Code check of the LLM judgment: passed, revised (fixed after one retry), flagged (still failing; never a requirement), skipped.';
COMMENT ON COLUMN analysis_features.facts IS 'Factual comparison sentences computed by code.';
COMMENT ON COLUMN analysis_features.coverage IS 'Which evidence views are missing for this feature.';

CREATE TABLE IF NOT EXISTS analysis_requirements (
  run_id            TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  req_id            TEXT NOT NULL,
  attribute         TEXT NOT NULL,
  title             TEXT NOT NULL,
  statement         TEXT NOT NULL,
  customer_value    TEXT,
  sub_theme         TEXT,
  assessment        TEXT NOT NULL,
  change_intent     TEXT NOT NULL,
  baseline_status   TEXT NOT NULL,
  baseline_rationale TEXT,
  target_operator   TEXT,
  target_value      DOUBLE PRECISION,
  target_unit       TEXT,
  target_condition  TEXT,
  target_rule       TEXT,
  lower_is_better   BOOLEAN NOT NULL,
  options           JSONB NOT NULL DEFAULT '[]'::jsonb,
  acceptance        JSONB,
  customer_facts    TEXT[] NOT NULL DEFAULT '{}',
  open_points       TEXT[] NOT NULL DEFAULT '{}',
  evidence_ids      TEXT[] NOT NULL DEFAULT '{}',
  regions           TEXT[] NOT NULL DEFAULT '{}',
  priority          TEXT NOT NULL,
  status            TEXT NOT NULL,
  wording           TEXT NOT NULL,
  PRIMARY KEY (run_id, req_id)
);
COMMENT ON TABLE analysis_requirements IS 'Recommended requirement candidates for the successor model (output of candidate_agent), one per recommended feature.';
COMMENT ON COLUMN analysis_requirements.req_id IS 'REQ-<n>, in importance order.';
COMMENT ON COLUMN analysis_requirements.statement IS 'Quantitative requirement text: the target, or without one the customer share behind it.';
COMMENT ON COLUMN analysis_requirements.change_intent IS 'introduce (new), improve, retain (keep a strength), remove.';
COMMENT ON COLUMN analysis_requirements.baseline_status IS 'Whether the current model has the feature: known_present, known_absent, unknown.';
COMMENT ON COLUMN analysis_requirements.target_value IS 'Proposed target value (with operator, unit and test condition, e.g. <= 25 min at 10-80%; bev). NULL: no comparable number, the PM sets it.';
COMMENT ON COLUMN analysis_requirements.target_rule IS 'Why this target, e.g. competitor median (gap) or today''s value.';
COMMENT ON COLUMN analysis_requirements.options IS 'Target options the PM can choose: ours, competitor_median, best_in_class (value, unit, condition).';
COMMENT ON COLUMN analysis_requirements.acceptance IS 'Acceptance criterion: metric, operator, target, verification method, test conditions.';
COMMENT ON COLUMN analysis_requirements.evidence_ids IS 'Finding ids (analysis_findings) the requirement is based on.';
COMMENT ON COLUMN analysis_requirements.wording IS 'llm = worded by an LLM and checked by code; template = worded by code.';

CREATE TABLE IF NOT EXISTS analysis_findings (
  run_id        TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  finding_id    TEXT NOT NULL,
  agent         TEXT NOT NULL,
  attribute     TEXT NOT NULL,
  subject       TEXT NOT NULL,
  claim         TEXT NOT NULL,
  polarity      TEXT,
  direction     TEXT,
  region        TEXT,
  confidence    TEXT,
  value         DOUBLE PRECISION,
  unit          TEXT,
  qualifier     TEXT,
  value_origin  TEXT,
  k             INTEGER,
  n             INTEGER,
  ci_low        DOUBLE PRECISION,
  ci_high       DOUBLE PRECISION,
  thin          BOOLEAN,
  denominator   TEXT,
  horizon       TEXT,
  PRIMARY KEY (run_id, finding_id)
);
COMMENT ON TABLE analysis_findings IS 'Every single claim of the four agents, each traceable to sources: baseline (our current model: catalog, sales, studies), competition (competitor values), feedback (customer shares), trends (market and regulation).';
COMMENT ON COLUMN analysis_findings.agent IS 'baseline, competition, feedback or trends.';
COMMENT ON COLUMN analysis_findings.subject IS 'What the claim is about: the BMW model code, a competitor model, customers, or market.';
COMMENT ON COLUMN analysis_findings.direction IS 'Customer view: problem, request, strength, neutral.';
COMMENT ON COLUMN analysis_findings.region IS 'Region the finding is about; NULL = all regions of the run.';
COMMENT ON COLUMN analysis_findings.value IS 'The number of the claim, if any, in unit; for customer shares a fraction 0-1 (k of n).';
COMMENT ON COLUMN analysis_findings.qualifier IS 'Test standard, variant, powertrain, period or region of the value, e.g. "WLTP; variant i5 eDrive40; powertrain bev".';
COMMENT ON COLUMN analysis_findings.value_origin IS 'record = stored data value; computed = derived by code; source_text = stated in the cited text and checked.';
COMMENT ON COLUMN analysis_findings.ci_low IS 'Wilson 95% interval lower bound of a customer share.';
COMMENT ON COLUMN analysis_findings.thin IS 'Small sample: treat with caution.';

CREATE TABLE IF NOT EXISTS analysis_sources (
  run_id        TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  source_id     TEXT NOT NULL,
  kind          TEXT NOT NULL,
  source_type   TEXT,
  title         TEXT,
  ref           TEXT NOT NULL,
  url           TEXT,
  excerpt       TEXT NOT NULL,
  locator       JSONB,
  retrieved_at  TIMESTAMPTZ,
  limitations   TEXT[] NOT NULL DEFAULT '{}',
  PRIMARY KEY (run_id, source_id)
);
COMMENT ON TABLE analysis_sources IS 'Evidence behind the findings and judgments: BMW catalog rows, study and sales cells, competitor web pages, and the customer feedback items a judgment or requirement cites (plus one example per sub-theme; quote texts are in analysis_quotes). Excerpts are capped at 600 characters.';
COMMENT ON COLUMN analysis_sources.kind IS 'feedback (customer feedback item), ontology (BMW catalog / study / sales record), web (competitor or trend web page), sql.';
COMMENT ON COLUMN analysis_sources.source_type IS 'Finer type: customer_feedback, product_catalog, customer_study, sales_dataset, web_page, model_record.';
COMMENT ON COLUMN analysis_sources.excerpt IS 'Verbatim text the findings rely on (feedback text, catalog row, quoted web sentence).';
COMMENT ON COLUMN analysis_sources.locator IS 'Where in the original: PDF page, spreadsheet cell, web text fragment.';

CREATE TABLE IF NOT EXISTS analysis_finding_sources (
  run_id      TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  finding_id  TEXT NOT NULL,
  source_id   TEXT NOT NULL,
  PRIMARY KEY (run_id, finding_id, source_id)
);
COMMENT ON TABLE analysis_finding_sources IS 'Which sources each finding cites (join analysis_findings with analysis_sources).';

CREATE TABLE IF NOT EXISTS analysis_customer_signals (
  run_id        TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  attribute     TEXT NOT NULL,
  finding_id    TEXT NOT NULL,
  direction     TEXT NOT NULL,
  region        TEXT,
  share         DOUBLE PRECISION NOT NULL,
  k             INTEGER NOT NULL,
  n             INTEGER NOT NULL,
  ci_low        DOUBLE PRECISION NOT NULL,
  ci_high       DOUBLE PRECISION NOT NULL,
  thin          BOOLEAN NOT NULL,
  differs_from  TEXT,
  p_value       DOUBLE PRECISION,
  PRIMARY KEY (run_id, finding_id)
);
COMMENT ON TABLE analysis_customer_signals IS 'Customer feedback shares per feature: share of feedback items reporting a problem, a request or praise (k of n, 95% interval), per region.';
COMMENT ON COLUMN analysis_customer_signals.region IS 'NULL = pooled over all regions of the run.';
COMMENT ON COLUMN analysis_customer_signals.differs_from IS 'Other regions this share differs from significantly (two-proportion test).';

CREATE TABLE IF NOT EXISTS analysis_competitor_values (
  run_id          TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  attribute       TEXT NOT NULL,
  ordinal         INTEGER NOT NULL,
  unit            TEXT NOT NULL,
  condition       TEXT NOT NULL,
  region          TEXT,
  n               INTEGER NOT NULL,
  minimum         DOUBLE PRECISION NOT NULL,
  median          DOUBLE PRECISION NOT NULL,
  maximum         DOUBLE PRECISION NOT NULL,
  lower_is_better BOOLEAN NOT NULL,
  ours            DOUBLE PRECISION,
  ours_rank       INTEGER,
  field_size      INTEGER,
  ours_vs_median  DOUBLE PRECISION,
  finding_ids     TEXT[] NOT NULL,
  PRIMARY KEY (run_id, attribute, ordinal)
);
COMMENT ON TABLE analysis_competitor_values IS 'Like-for-like competitor comparisons per feature: values with the same unit, test standard and powertrain, and our best current value against them.';
COMMENT ON COLUMN analysis_competitor_values.condition IS 'Comparison basis: test standard and powertrain, e.g. "wltp; bev". Values under different conditions are never compared.';
COMMENT ON COLUMN analysis_competitor_values.ours IS 'Our best current variant in this comparison (NULL if we have no comparable value).';
COMMENT ON COLUMN analysis_competitor_values.ours_rank IS '1 = best among competitors and ours.';
COMMENT ON COLUMN analysis_competitor_values.ours_vs_median IS '(ours - median) / |median|.';

CREATE TABLE IF NOT EXISTS analysis_quotes (
  run_id      TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  attribute   TEXT NOT NULL,
  ordinal     INTEGER NOT NULL,
  source_id   TEXT NOT NULL,
  direction   TEXT,
  text        TEXT NOT NULL,
  PRIMARY KEY (run_id, attribute, ordinal)
);
COMMENT ON TABLE analysis_quotes IS 'Representative customer feedback per feature, alternating problem / request / praise so counter-evidence is included. Verbatim.';

CREATE TABLE IF NOT EXISTS analysis_sub_themes (
  run_id      TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  attribute   TEXT NOT NULL,
  ordinal     INTEGER NOT NULL,
  direction   TEXT NOT NULL,
  name        TEXT NOT NULL,
  k           INTEGER NOT NULL,
  of_total    INTEGER NOT NULL,
  method      TEXT NOT NULL,
  source_ids  TEXT[] NOT NULL DEFAULT '{}',
  PRIMARY KEY (run_id, attribute, ordinal)
);
COMMENT ON TABLE analysis_sub_themes IS 'What exactly customers mean within a feature and direction, e.g. "winter range" within real_world_range problems: k of of_total items.';
COMMENT ON COLUMN analysis_sub_themes.method IS 'aspect_term = counted from extracted aspect terms; llm = grouped by an LLM on a sample.';

CREATE TABLE IF NOT EXISTS analysis_trends (
  run_id      TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  attribute   TEXT NOT NULL,
  finding_id  TEXT NOT NULL,
  claim       TEXT NOT NULL,
  polarity    TEXT,
  horizon     TEXT,
  n_independent_sources INTEGER,
  thin        BOOLEAN NOT NULL,
  PRIMARY KEY (run_id, attribute, finding_id)
);
COMMENT ON TABLE analysis_trends IS 'Market, technology and regulation trends relevant to a feature for a launch in 3-5 years.';

CREATE INDEX IF NOT EXISTS analysis_findings_attribute_idx ON analysis_findings (run_id, attribute);
CREATE INDEX IF NOT EXISTS analysis_requirements_attribute_idx ON analysis_requirements (run_id, attribute);

-- Feature list with its recommendation: the entry point for a UI list and for LLM questions.
DROP VIEW IF EXISTS analysis_feature_overview;
CREATE VIEW analysis_feature_overview AS
SELECT f.run_id, f.rank, f.attribute, f.label, f.area, f.assessment, f.method, f.certainty,
       f.what_exactly, r.req_id, r.statement AS requirement, r.change_intent,
       r.target_operator, r.target_value, r.target_unit, r.target_condition,
       (SELECT COALESCE(MAX(s.share) FILTER (WHERE s.direction = 'problem' AND s.region IS NULL),
                        MAX(s.share) FILTER (WHERE s.direction = 'problem'))
          FROM analysis_customer_signals s
         WHERE s.run_id = f.run_id AND s.attribute = f.attribute) AS problem_share,
       (SELECT COUNT(*) FROM analysis_competitor_values c
         WHERE c.run_id = f.run_id AND c.attribute = f.attribute) AS n_competitor_comparisons
  FROM analysis_features f
  LEFT JOIN analysis_requirements r ON r.run_id = f.run_id AND r.attribute = f.attribute;
COMMENT ON VIEW analysis_feature_overview IS 'One row per feature with its assessment and, if recommended, its requirement (req_id not NULL). problem_share: share of feedback items reporting a problem, pooled over regions (or the largest regional share in a one-region run).';
