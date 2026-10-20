-- Additive PostgreSQL migration; startup also adds these nullable model columns idempotently.
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS number_rotation_enabled boolean;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS caller_number_pool json;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS retry_caller_policy varchar(16);
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS caller_rotation_cursor integer;
-- NULL keeps rotation off; existing campaigns, agent overrides, and defaults are unchanged.
