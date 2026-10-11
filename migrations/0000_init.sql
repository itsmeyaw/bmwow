-- Idempotent: scripts/preprocess.ts applies this on every run.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS feedback_entries (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feedback_explorer_id TEXT NOT NULL UNIQUE,
  source               TEXT,
  brand                TEXT,
  sales_description    TEXT,
  country              TEXT,
  derivate_code        TEXT,
  engine_type          TEXT,
  raw_feedback         TEXT NOT NULL,
  embedding            vector(1536),
  search_tsv           tsvector GENERATED ALWAYS AS (to_tsvector('english', raw_feedback)) STORED,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedback_aspects (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feedback_entry_id UUID NOT NULL REFERENCES feedback_entries(id) ON DELETE CASCADE,
  feedback_type     TEXT,
  vfc_category      TEXT NOT NULL,
  aspect_term       TEXT,
  aspect_label_raw  TEXT,
  issue_type        TEXT NOT NULL,
  quote_snippet     TEXT,
  sentiment         TEXT NOT NULL CHECK (sentiment IN ('Positive', 'Negative', 'Neutral')),
  sentiment_score   NUMERIC(3,2) CHECK (sentiment_score BETWEEN -1 AND 1),
  extraction_source TEXT NOT NULL CHECK (extraction_source IN ('vfc_label', 'llm')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS feedback_entries_derivate_engine_idx ON feedback_entries (derivate_code, engine_type);
CREATE INDEX IF NOT EXISTS feedback_entries_embedding_idx ON feedback_entries USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS feedback_entries_search_tsv_idx ON feedback_entries USING gin (search_tsv);
CREATE INDEX IF NOT EXISTS feedback_aspects_category_sentiment_idx ON feedback_aspects (vfc_category, sentiment);
CREATE INDEX IF NOT EXISTS feedback_aspects_entry_idx ON feedback_aspects (feedback_entry_id);
