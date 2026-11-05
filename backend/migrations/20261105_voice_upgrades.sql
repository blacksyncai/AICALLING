-- The normal schema startup also creates/adds these idempotently.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS pronunciations JSON;
CREATE TABLE IF NOT EXISTS account_voices (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    voice_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    language VARCHAR(8) NOT NULL DEFAULT 'en',
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_account_voices_org_id ON account_voices (org_id);
