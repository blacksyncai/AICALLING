-- Additive PostgreSQL migration; startup also adds these nullable model columns idempotently.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS billing_country varchar(8);
-- NULL = US default (Stripe). "CA" | "OTHER" route one-time purchases through Helcim.
