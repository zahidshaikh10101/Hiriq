-- Hiriq schema (PostgreSQL). Generated from app/db/models.py; do not edit by hand.

CREATE TABLE plans (
	id VARCHAR(20) NOT NULL, 
	name VARCHAR(40) NOT NULL, 
	live BOOLEAN DEFAULT false NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE users (
	id UUID NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	username VARCHAR(40), 
	full_name VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(255), 
	phone_e164 VARCHAR(20), 
	email_verified BOOLEAN DEFAULT false NOT NULL, 
	phone_verified BOOLEAN DEFAULT false NOT NULL, 
	role VARCHAR(20) DEFAULT 'candidate' NOT NULL, 
	status VARCHAR(20) DEFAULT 'active' NOT NULL, 
	plan_id VARCHAR(20) DEFAULT 'free' NOT NULL, 
	designation VARCHAR(120), 
	company VARCHAR(120), 
	job_alerts BOOLEAN DEFAULT true NOT NULL, 
	consented_at TIMESTAMP WITH TIME ZONE, 
	failed_logins INTEGER DEFAULT '0' NOT NULL, 
	locked_until TIMESTAMP WITH TIME ZONE, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_users_role CHECK (role IN ('candidate', 'recruiter', 'admin')), 
	CONSTRAINT ck_users_status CHECK (status IN ('active', 'suspended', 'invited')), 
	CONSTRAINT ck_users_email_lower CHECK (email = lower(email)), 
	UNIQUE (email), 
	UNIQUE (username), 
	FOREIGN KEY(plan_id) REFERENCES plans (id)
);

CREATE INDEX ix_users_phone_e164 ON users (phone_e164);

CREATE INDEX ix_users_role_status ON users (role, status);

CREATE TABLE admin_invites (
	id UUID NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	full_name VARCHAR(120), 
	phone_e164 VARCHAR(20), 
	designation VARCHAR(120), 
	company VARCHAR(120), 
	role VARCHAR(20) DEFAULT 'candidate' NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	invited_by UUID, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	accepted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_invite_role CHECK (role IN ('candidate', 'recruiter', 'admin')), 
	UNIQUE (token_hash), 
	FOREIGN KEY(invited_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_admin_invites_email ON admin_invites (email);

CREATE TABLE admin_profiles (
	user_id UUID NOT NULL, 
	is_superadmin BOOLEAN DEFAULT false NOT NULL, 
	permissions JSONB NOT NULL, 
	invited_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(invited_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE audit_logs (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	category VARCHAR(20) NOT NULL, 
	actor_id UUID, 
	actor_label VARCHAR(120) DEFAULT 'system' NOT NULL, 
	action TEXT NOT NULL, 
	target_user_id UUID, 
	ip VARCHAR(45), 
	meta JSONB, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_audit_category CHECK (category IN ('Auth', 'Users', 'Model', 'Data')), 
	FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(target_user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_category_created ON audit_logs (category, created_at);

CREATE INDEX ix_audit_created ON audit_logs (created_at);

CREATE TABLE auth_identities (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	provider VARCHAR(20) NOT NULL, 
	subject VARCHAR(255) NOT NULL, 
	email VARCHAR(320), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_identity_provider_subject UNIQUE (provider, subject), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_identities_user_id ON auth_identities (user_id);

CREATE TABLE otp_codes (
	id UUID NOT NULL, 
	purpose VARCHAR(20) NOT NULL, 
	destination VARCHAR(320) NOT NULL, 
	user_id UUID, 
	code_hash VARCHAR(64) NOT NULL, 
	attempts INTEGER DEFAULT '0' NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_otp_purpose CHECK (purpose IN ('signup')), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_otp_destination_created ON otp_codes (destination, created_at);

INSERT INTO plans (id, name, live) VALUES
  ('free','Free',true),('basic','Basic',false),('pro','Pro',false),('premium','Premium',false)
ON CONFLICT (id) DO NOTHING;
