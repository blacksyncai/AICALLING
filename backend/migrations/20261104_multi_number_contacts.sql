-- The normal schema startup also adds these nullable columns idempotently.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS phones JSON;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS try_other_numbers BOOLEAN;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS rounds_per_number INTEGER;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS number_gap_minutes INTEGER;
