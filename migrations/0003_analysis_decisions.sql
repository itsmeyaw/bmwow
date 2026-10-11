-- Idempotent: src/server/situation/decisions.ts applies this before its first write.
-- PM decisions taken in the chat about a stored run. The run itself (analysis_*) is never changed;
-- the report applies the active decisions on top of it. Undo marks a row, it does not delete it.

CREATE TABLE IF NOT EXISTS analysis_decisions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id      TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
  req_id      TEXT,
  attribute   TEXT NOT NULL,
  action      TEXT NOT NULL CHECK (action IN ('omit', 'change_target', 'deprioritize', 'note')),
  operator    TEXT CHECK (operator IN ('>=', '<=', '=')),
  value       DOUBLE PRECISION,
  unit        TEXT,
  reason      TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  undone_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS analysis_decisions_run_idx ON analysis_decisions (run_id, created_at);

COMMENT ON TABLE analysis_decisions IS 'Decisions a PM took in the chat about a run''s recommendations (omit a requirement, change its target, deprioritize, or add a note). The recorded run is unchanged; active rows (undone_at IS NULL) adapt the report.';
COMMENT ON COLUMN analysis_decisions.req_id IS 'REQ-n of analysis_requirements, if the decision concerns a recommended requirement.';
COMMENT ON COLUMN analysis_decisions.attribute IS 'Feature key (analysis_features.attribute).';
COMMENT ON COLUMN analysis_decisions.action IS 'omit = drop the requirement; change_target = PM-set target (operator, value, unit); deprioritize = keep with low priority; note = remark or constraint without changing the requirement.';
COMMENT ON COLUMN analysis_decisions.reason IS 'Why, in the PM''s words as summarised by the chat.';
COMMENT ON COLUMN analysis_decisions.undone_at IS 'Set when the PM undid the decision; NULL = active.';
