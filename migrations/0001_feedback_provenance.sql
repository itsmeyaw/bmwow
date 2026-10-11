-- Additive feedback history. Existing imports remain readable with unknown provenance.
CREATE TABLE IF NOT EXISTS feedback_revisions (
  id UUID PRIMARY KEY,
  feedback_explorer_id TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  processing_hash TEXT NOT NULL,
  payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  embedding vector(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (feedback_explorer_id, input_hash, processing_hash)
);
CREATE INDEX IF NOT EXISTS feedback_revisions_identity_idx ON feedback_revisions (feedback_explorer_id);
CREATE INDEX IF NOT EXISTS feedback_revisions_aspects_idx ON feedback_revisions USING gin ((payload->'aspects') jsonb_path_ops);
ALTER TABLE feedback_entries ADD COLUMN IF NOT EXISTS revision_id UUID REFERENCES feedback_revisions(id);
ALTER TABLE feedback_entries ADD COLUMN IF NOT EXISTS provenance JSONB;
