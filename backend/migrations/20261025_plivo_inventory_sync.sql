-- Also applied idempotently by schema startup; nullable for existing records.
ALTER TABLE phone_numbers ADD COLUMN IF NOT EXISTS provider_missing_since TIMESTAMPTZ;
ALTER TABLE phone_numbers ADD COLUMN IF NOT EXISTS provider_check_account VARCHAR(64);
ALTER TABLE phone_numbers ADD COLUMN IF NOT EXISTS provider_cleanup_pending BOOLEAN;
