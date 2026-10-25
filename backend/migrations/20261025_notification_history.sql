-- The normal schema startup also adds these nullable columns idempotently.
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS notification_key VARCHAR(160);
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS from_email VARCHAR(320);
CREATE INDEX IF NOT EXISTS ix_email_messages_notification_key ON email_messages (notification_key);
ALTER TABLE call_alerts ADD COLUMN IF NOT EXISTS copy_status VARCHAR(16);
ALTER TABLE call_alerts ADD COLUMN IF NOT EXISTS copy_to VARCHAR(320);
ALTER TABLE call_alerts ADD COLUMN IF NOT EXISTS copy_error TEXT;
ALTER TABLE call_alerts ADD COLUMN IF NOT EXISTS copy_attempted_at TIMESTAMPTZ;
