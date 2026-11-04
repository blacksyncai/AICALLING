-- The normal schema startup also adds these idempotently.
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS admin_until TIMESTAMPTZ;
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS admin_org_id UUID;
CREATE TABLE IF NOT EXISTS admin_mcp_actions (
    id UUID PRIMARY KEY,
    token_id UUID,
    admin_id UUID REFERENCES users(id) ON DELETE SET NULL,
    org_id UUID,
    org_name VARCHAR(200) NOT NULL DEFAULT '',
    tool VARCHAR(80) NOT NULL,
    read_only BOOLEAN NOT NULL DEFAULT TRUE,
    arguments TEXT NOT NULL DEFAULT '',
    ok BOOLEAN NOT NULL DEFAULT TRUE,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_admin_mcp_actions_token_id ON admin_mcp_actions (token_id);
CREATE INDEX IF NOT EXISTS ix_admin_mcp_actions_org_id ON admin_mcp_actions (org_id);
CREATE INDEX IF NOT EXISTS ix_admin_mcp_actions_created_at ON admin_mcp_actions (created_at);
