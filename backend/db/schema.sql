-- Hiriq schema (PostgreSQL). Generated from app/db/models.py and app/db/recruiter_models.py; do not edit by hand.

CREATE TABLE external_jobs (
	id UUID NOT NULL, 
	provider VARCHAR(30) NOT NULL, 
	external_id VARCHAR(200) NOT NULL, 
	title VARCHAR(160) NOT NULL, 
	company VARCHAR(160), 
	location VARCHAR(160), 
	country VARCHAR(2), 
	remote BOOLEAN NOT NULL, 
	apply_url VARCHAR(600), 
	description TEXT NOT NULL, 
	posted_at TIMESTAMP WITH TIME ZONE, 
	read JSONB NOT NULL, 
	last_query VARCHAR(100), 
	first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_external_job_provider_id UNIQUE (provider, external_id)
);

CREATE INDEX ix_external_jobs_last_seen ON external_jobs (last_seen_at);

CREATE INDEX ix_external_jobs_title ON external_jobs (title);

CREATE TABLE pending_signups (
	id UUID NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	full_name VARCHAR(120) NOT NULL, 
	date_of_birth DATE NOT NULL, 
	phone_e164 VARCHAR(20), 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	job_alerts BOOLEAN DEFAULT false NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	consented_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_pending_role CHECK (role IN ('candidate', 'recruiter')), 
	UNIQUE (email)
);

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
	date_of_birth DATE, 
	designation VARCHAR(120), 
	company VARCHAR(120), 
	job_alerts BOOLEAN DEFAULT false NOT NULL, 
	consented_at TIMESTAMP WITH TIME ZONE, 
	failed_logins INTEGER DEFAULT '0' NOT NULL, 
	locked_until TIMESTAMP WITH TIME ZONE, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	tokens_valid_after TIMESTAMP WITH TIME ZONE, 
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

CREATE TABLE ai_calls (
	id BIGSERIAL NOT NULL, 
	owner_id UUID, 
	purpose VARCHAR(20) NOT NULL, 
	model VARCHAR(120) NOT NULL, 
	ok BOOLEAN NOT NULL, 
	error VARCHAR(200), 
	latency_ms INTEGER, 
	prompt_tokens INTEGER, 
	completion_tokens INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_ai_calls_owner_purpose_created ON ai_calls (owner_id, purpose, created_at);

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

CREATE TABLE candidates (
	id UUID NOT NULL, 
	owner_id UUID, 
	user_id UUID, 
	source VARCHAR(10) DEFAULT 'upload' NOT NULL, 
	full_name VARCHAR(160) NOT NULL, 
	email VARCHAR(320), 
	phone VARCHAR(30), 
	location VARCHAR(160), 
	linkedin_url VARCHAR(300), 
	github_url VARCHAR(300), 
	current_title VARCHAR(160), 
	current_company VARCHAR(160), 
	total_experience_years FLOAT, 
	qualification VARCHAR(200), 
	skills JSONB NOT NULL, 
	profile JSONB, 
	resume_text TEXT, 
	file_name VARCHAR(255), 
	file_hash VARCHAR(64), 
	visible_to_recruiters BOOLEAN DEFAULT false NOT NULL, 
	is_demo BOOLEAN DEFAULT false NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_candidates_source CHECK (source IN ('upload', 'platform')), 
	CONSTRAINT uq_candidate_owner_filehash UNIQUE (owner_id, file_hash), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_candidates_owner_created ON candidates (owner_id, created_at);

CREATE TABLE external_calls (
	id BIGSERIAL NOT NULL, 
	owner_id UUID, 
	provider VARCHAR(30) DEFAULT 'indeed' NOT NULL, 
	ok BOOLEAN NOT NULL, 
	error VARCHAR(200), 
	latency_ms INTEGER, 
	results INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_external_calls_created ON external_calls (created_at);

CREATE TABLE jobs (
	id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	title VARCHAR(160) NOT NULL, 
	department VARCHAR(120), 
	location VARCHAR(120), 
	work_mode VARCHAR(20), 
	employment_type VARCHAR(30), 
	experience_min INTEGER, 
	experience_max INTEGER, 
	qualification VARCHAR(200), 
	salary_min INTEGER, 
	salary_max INTEGER, 
	salary_currency VARCHAR(3) DEFAULT 'INR' NOT NULL, 
	skills_required JSONB NOT NULL, 
	skills_nice JSONB NOT NULL, 
	responsibilities TEXT, 
	description TEXT, 
	status VARCHAR(10) DEFAULT 'draft' NOT NULL, 
	is_demo BOOLEAN DEFAULT false NOT NULL, 
	opened_at TIMESTAMP WITH TIME ZONE, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_jobs_status CHECK (status IN ('draft', 'open', 'closed')), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_jobs_owner_status ON jobs (owner_id, status);

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
	CONSTRAINT ck_otp_purpose CHECK (purpose IN ('signup', 'reset')), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_otp_destination_created ON otp_codes (destination, created_at);

CREATE TABLE applications (
	id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	candidate_id UUID NOT NULL, 
	resume_label VARCHAR(120) NOT NULL, 
	resume_text TEXT NOT NULL, 
	letter_label VARCHAR(120), 
	letter_text TEXT, 
	message TEXT, 
	contact JSONB NOT NULL, 
	fit_score FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_application_job_candidate UNIQUE (job_id, candidate_id), 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE
);

CREATE INDEX ix_applications_candidate_created ON applications (candidate_id, created_at);

CREATE INDEX ix_applications_job_created ON applications (job_id, created_at);

CREATE TABLE candidate_job_matches (
	id UUID NOT NULL, 
	candidate_id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	score FLOAT NOT NULL, 
	breakdown JSONB, 
	explanation JSONB, 
	model_version VARCHAR(40), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cmatch_candidate_job UNIQUE (candidate_id, job_id), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE, 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
);

CREATE INDEX ix_cmatch_candidate_score ON candidate_job_matches (candidate_id, score);

CREATE TABLE cover_letters (
	id UUID NOT NULL, 
	candidate_id UUID NOT NULL, 
	job_id UUID, 
	job_title VARCHAR(200), 
	label VARCHAR(120) NOT NULL, 
	tone VARCHAR(20) DEFAULT 'professional' NOT NULL, 
	text TEXT NOT NULL, 
	content JSONB NOT NULL, 
	model VARCHAR(80), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE, 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE SET NULL
);

CREATE INDEX ix_cover_letters_candidate_created ON cover_letters (candidate_id, created_at);

CREATE TABLE interview_preps (
	id UUID NOT NULL, 
	candidate_id UUID NOT NULL, 
	job_id UUID, 
	job_title VARCHAR(200), 
	content JSONB NOT NULL, 
	model VARCHAR(80), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE, 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE SET NULL
);

CREATE INDEX ix_interview_preps_candidate_created ON interview_preps (candidate_id, created_at);

CREATE TABLE job_matches (
	id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	candidate_id UUID NOT NULL, 
	score FLOAT NOT NULL, 
	breakdown JSONB, 
	explanation JSONB, 
	model_version VARCHAR(40), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_match_job_candidate UNIQUE (job_id, candidate_id), 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE
);

CREATE INDEX ix_matches_job_score ON job_matches (job_id, score);

CREATE TABLE match_feedback (
	id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	candidate_id UUID NOT NULL, 
	recruiter_id UUID NOT NULL, 
	label INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_feedback_label CHECK (label IN (-1, 1)), 
	CONSTRAINT uq_feedback_once UNIQUE (job_id, candidate_id, recruiter_id), 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE, 
	FOREIGN KEY(recruiter_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE pipeline_entries (
	id UUID NOT NULL, 
	job_id UUID NOT NULL, 
	candidate_id UUID NOT NULL, 
	stage VARCHAR(20) DEFAULT 'sourced' NOT NULL, 
	reached INTEGER DEFAULT '0' NOT NULL, 
	rejection_reason VARCHAR(200), 
	note TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_pipeline_stage CHECK (stage IN ('sourced', 'shortlisted', 'interview', 'offer', 'hired', 'rejected')), 
	CONSTRAINT uq_pipeline_job_candidate UNIQUE (job_id, candidate_id), 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE
);

CREATE INDEX ix_pipeline_job_stage ON pipeline_entries (job_id, stage);

CREATE TABLE recruiter_events (
	id BIGSERIAL NOT NULL, 
	owner_id UUID NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	text TEXT NOT NULL, 
	job_id UUID, 
	candidate_id UUID, 
	is_demo BOOLEAN DEFAULT false NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_recruiter_event_kind CHECK (kind IN ('job', 'resume', 'match', 'pipeline')), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE SET NULL, 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE SET NULL
);

CREATE INDEX ix_recruiter_events_owner_created ON recruiter_events (owner_id, created_at);

CREATE TABLE resume_versions (
	id UUID NOT NULL, 
	candidate_id UUID NOT NULL, 
	job_id UUID, 
	job_title VARCHAR(200), 
	label VARCHAR(120) NOT NULL, 
	content JSONB NOT NULL, 
	text TEXT NOT NULL, 
	score_before FLOAT, 
	score_after FLOAT, 
	model VARCHAR(80), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE, 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE SET NULL
);

CREATE INDEX ix_resume_versions_candidate_created ON resume_versions (candidate_id, created_at);

INSERT INTO plans (id, name, live) VALUES
  ('free','Free',true),('basic','Basic',false),('pro','Pro',false),('premium','Premium',false)
ON CONFLICT (id) DO NOTHING;
