-- Additive PostgreSQL migration; startup also adds these nullable model columns idempotently.
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS warmup_enabled boolean;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS warmup_min_gap_seconds integer;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS warmup_max_gap_seconds integer;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS warmup_batch_size integer;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS warmup_rest_seconds integer;
-- NULL keeps warm-up off; existing campaigns dial exactly as before.
