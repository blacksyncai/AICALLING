-- Forward-only companion to create_all_tables(); safe to replay.
-- Startup automatically applies these additive tables; no existing data is rewritten.

CREATE TABLE IF NOT EXISTS registration_authorizations (
	id UUID NOT NULL,
	org_id UUID NOT NULL,
	caller_name VARCHAR(15) NOT NULL,
	legal_name VARCHAR(255) NOT NULL,
	details JSON NOT NULL,
	providers JSON NOT NULL,
	fees_authorized JSON NOT NULL,
	authorized_by UUID NOT NULL,
	evidence TEXT NOT NULL,
	terms_version VARCHAR(32) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE,
	FOREIGN KEY(authorized_by) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_registration_authorizations_org_id ON registration_authorizations (org_id);

CREATE TABLE IF NOT EXISTS registration_businesses (
	id UUID NOT NULL,
	org_id UUID NOT NULL,
	provider VARCHAR(32) NOT NULL,
	external_id VARCHAR(255),
	status VARCHAR(32) NOT NULL,
	response JSON NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_registration_business UNIQUE (org_id, provider),
	FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_registration_businesses_org_id ON registration_businesses (org_id);

CREATE TABLE IF NOT EXISTS number_registrations (
	id UUID NOT NULL,
	phone_number_id UUID NOT NULL,
	org_id UUID NOT NULL,
	assignment_key VARCHAR(64) NOT NULL,
	number VARCHAR(20) NOT NULL,
	carrier VARCHAR(32) NOT NULL,
	carrier_number_id VARCHAR(64),
	provider VARCHAR(32) NOT NULL,
	authorization_id UUID,
	caller_name VARCHAR(15) NOT NULL,
	phase VARCHAR(16) NOT NULL,
	status VARCHAR(32) NOT NULL,
	prerequisite TEXT NOT NULL,
	request_id VARCHAR(255),
	previous_request_id VARCHAR(255),
	submission_intent_at TIMESTAMP WITH TIME ZONE,
	removal_intent_at TIMESTAMP WITH TIME ZONE,
	attempts INTEGER NOT NULL,
	next_at TIMESTAMP WITH TIME ZONE NOT NULL,
	lease_until TIMESTAMP WITH TIME ZONE,
	lease_token VARCHAR(64),
	response JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_number_registration_assignment UNIQUE (phone_number_id, assignment_key, provider),
	FOREIGN KEY(phone_number_id) REFERENCES phone_numbers (id) ON DELETE CASCADE,
	FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE CASCADE,
	FOREIGN KEY(authorization_id) REFERENCES registration_authorizations (id)
);

CREATE INDEX IF NOT EXISTS ix_number_registrations_next_at ON number_registrations (next_at);

CREATE INDEX IF NOT EXISTS ix_number_registrations_org_id ON number_registrations (org_id);

CREATE INDEX IF NOT EXISTS ix_number_registrations_phone_number_id ON number_registrations (phone_number_id);

CREATE INDEX IF NOT EXISTS ix_number_registrations_status ON number_registrations (status);

CREATE TABLE IF NOT EXISTS registration_receipts (
	id UUID NOT NULL,
	registration_id UUID NOT NULL,
	method VARCHAR(8) NOT NULL,
	path TEXT NOT NULL,
	http_status INTEGER NOT NULL,
	request_id VARCHAR(255),
	response JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(registration_id) REFERENCES number_registrations (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_registration_receipts_registration_id ON registration_receipts (registration_id);
