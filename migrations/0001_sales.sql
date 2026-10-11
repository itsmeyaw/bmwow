-- Idempotent: scripts/import-sales.ts applies this inside its import transaction.
CREATE TABLE IF NOT EXISTS public.sales (
  model_code  TEXT NOT NULL,
  market_code TEXT NOT NULL,
  volume_2024 INTEGER NOT NULL CONSTRAINT sales_volume_2024_check CHECK (volume_2024 >= 0),
  volume_2025 INTEGER NOT NULL CONSTRAINT sales_volume_2025_check CHECK (volume_2025 >= 0),
  volume_2030 INTEGER NOT NULL CONSTRAINT sales_volume_2030_check CHECK (volume_2030 >= 0),
  source_file TEXT NOT NULL,
  source_row  INTEGER NOT NULL CONSTRAINT sales_source_row_check CHECK (source_row >= 2),
  PRIMARY KEY (model_code, market_code)
);
