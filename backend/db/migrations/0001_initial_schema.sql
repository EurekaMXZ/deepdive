-- DeepDive initial schema for PostgreSQL 18.
-- Requires the PostgreSQL 18 built-in uuidv7() function.

BEGIN;

CREATE TABLE config_snapshots (
    id uuid primary key default uuidv7(),
    config_version text not null,
    content_hash text not null,
    config_json jsonb not null,
    created_at timestamptz not null
);

CREATE TABLE analyses (
    id uuid primary key default uuidv7(),
    tenant_id uuid,
    created_by_user_id uuid,
    repository_url text not null,
    repository_url_hash text not null,
    requested_ref text not null,
    analysis_profile_id uuid,
    config_snapshot_id uuid not null,
    status text not null,
    created_at timestamptz not null,
    updated_at timestamptz not null,
    completed_at timestamptz,
    error_code text,
    error_message text
);

CREATE TABLE tenants (
    id uuid primary key default uuidv7(),
    slug text not null,
    display_name text not null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

CREATE TABLE users (
    id uuid primary key default uuidv7(),
    tenant_id uuid not null references tenants(id),
    email text not null,
    display_name text,
    is_active boolean not null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

CREATE TABLE user_credentials (
    id uuid primary key default uuidv7(),
    user_id uuid not null references users(id),
    password_hash text not null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

CREATE TABLE oauth_accounts (
    id uuid primary key default uuidv7(),
    tenant_id uuid not null references tenants(id),
    user_id uuid not null references users(id),
    provider text not null,
    provider_account_id text not null,
    provider_login text,
    provider_email text not null,
    provider_email_verified boolean not null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

CREATE TABLE refresh_tokens (
    id uuid primary key default uuidv7(),
    user_id uuid not null references users(id),
    token_hash text not null,
    expires_at timestamptz not null,
    revoked_at timestamptz,
    created_at timestamptz not null
);

CREATE TABLE permissions (
    id uuid primary key default uuidv7(),
    name text not null,
    description text not null,
    created_at timestamptz not null
);

CREATE TABLE roles (
    id uuid primary key default uuidv7(),
    tenant_id uuid references tenants(id),
    name text not null,
    description text not null,
    created_at timestamptz not null
);

CREATE TABLE role_permissions (
    id uuid primary key default uuidv7(),
    role_id uuid not null references roles(id),
    permission_id uuid not null references permissions(id),
    created_at timestamptz not null
);

CREATE TABLE user_roles (
    id uuid primary key default uuidv7(),
    user_id uuid not null references users(id),
    role_id uuid not null references roles(id),
    created_at timestamptz not null
);

CREATE TABLE audit_log (
    id uuid primary key default uuidv7(),
    tenant_id uuid references tenants(id),
    actor_user_id uuid references users(id),
    action text not null,
    resource_type text not null,
    resource_id uuid,
    payload_json jsonb not null,
    created_at timestamptz not null
);

CREATE TABLE snapshots (
    id uuid primary key default uuidv7(),
    tenant_id uuid,
    repository_url_hash text not null,
    requested_ref text not null,
    resolved_commit_sha text not null,
    tree_sha text not null,
    snapshot_policy_hash text not null,
    status text not null,
    manifest_key text,
    git_bundle_key text,
    file_count integer,
    total_bytes bigint,
    created_at timestamptz not null,
    ready_at timestamptz,
    error_code text,
    error_message text
);

CREATE TABLE agent_sessions (
    id uuid primary key default uuidv7(),
    analysis_id uuid not null references analyses(id),
    snapshot_id uuid,
    parent_agent_id uuid,
    config_snapshot_id uuid not null,
    status text not null,
    goal_ref text not null,
    effective_model text not null,
    effective_prompt_version text not null,
    effective_tool_registry_version text not null,
    effective_limits_json jsonb not null,
    effective_runtime_json jsonb not null,
    latest_response_id text,
    turn_count integer not null,
    max_turns integer not null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

CREATE TABLE agent_turns (
    id uuid primary key default uuidv7(),
    agent_id uuid not null references agent_sessions(id),
    turn_index integer not null,
    trigger_event_id uuid,
    trigger_domain_key text,
    status text not null,
    response_id text,
    previous_response_id text,
    input_ref text,
    output_ref text,
    input_token_count integer,
    output_token_count integer,
    total_token_count integer,
    created_at timestamptz not null,
    completed_at timestamptz
);

CREATE TABLE agent_stream_events (
    id uuid primary key default uuidv7(),
    analysis_id uuid not null references analyses(id),
    agent_id uuid not null references agent_sessions(id),
    turn_id uuid references agent_turns(id),
    seq bigint not null,
    event_type text not null,
    payload_json jsonb not null,
    attempt integer,
    response_id text,
    state text,
    created_at timestamptz not null
);

CREATE TABLE agent_context_items (
    id uuid primary key default uuidv7(),
    agent_id uuid not null references agent_sessions(id),
    turn_id uuid references agent_turns(id),
    seq bigint not null,
    item_type text not null,
    payload_json jsonb not null,
    response_id text,
    source text not null,
    idempotency_key text,
    compacted_at timestamptz,
    created_at timestamptz not null
);

CREATE TABLE context_assemblies (
    id uuid primary key default uuidv7(),
    agent_id uuid not null references agent_sessions(id),
    turn_id uuid not null references agent_turns(id),
    config_snapshot_id uuid not null,
    source_refs_json jsonb not null,
    input_ref text not null,
    instructions_hash text not null,
    tool_schema_hash text not null,
    token_estimate integer,
    created_at timestamptz not null
);

CREATE TABLE tool_calls (
    id uuid primary key default uuidv7(),
    agent_id uuid not null references agent_sessions(id),
    turn_id uuid not null references agent_turns(id),
    snapshot_id uuid not null,
    openai_call_id text not null,
    tool_name text not null,
    arguments_json jsonb not null,
    tool_registry_version text not null,
    tool_schema_hash text not null,
    tool_policy_hash text not null,
    permission_decision text,
    status text not null,
    result_ref text,
    result_summary text,
    duration_ms integer,
    error_code text,
    error_message text,
    claimed_at timestamptz,
    claim_expires_at timestamptz,
    claim_owner text,
    created_at timestamptz not null,
    completed_at timestamptz
);

CREATE TABLE evidence (
    id uuid primary key default uuidv7(),
    agent_id uuid not null references agent_sessions(id),
    snapshot_id uuid not null,
    tool_call_id uuid references tool_calls(id),
    path text not null,
    start_line integer,
    end_line integer,
    content_hash text,
    snippet_ref text,
    created_at timestamptz not null
);

CREATE TABLE documents (
    id uuid primary key default uuidv7(),
    analysis_id uuid not null references analyses(id),
    agent_id uuid not null references agent_sessions(id),
    title text not null,
    kind text not null,
    status text not null,
    current_version integer not null,
    content_ref text not null,
    content_hash text not null,
    size_bytes bigint not null,
    created_at timestamptz not null,
    updated_at timestamptz not null,
    finalized_at timestamptz
);

CREATE TABLE document_revisions (
    id uuid primary key default uuidv7(),
    document_id uuid not null references documents(id),
    version integer not null,
    tool_call_id uuid not null references tool_calls(id),
    operation text not null,
    content_ref text not null,
    content_hash text not null,
    size_bytes bigint not null,
    created_at timestamptz not null
);

CREATE TABLE memory_summaries (
    id uuid primary key default uuidv7(),
    agent_id uuid not null references agent_sessions(id),
    compacted_until_turn integer not null,
    summary_json jsonb not null,
    evidence_ids_json jsonb not null,
    focus_paths_json jsonb not null,
    next_action text,
    created_at timestamptz not null
);

CREATE TABLE outbox_events (
    id uuid primary key default uuidv7(),
    event_type text not null,
    payload_json jsonb not null,
    published_at timestamptz,
    created_at timestamptz not null
);

CREATE TABLE processed_events (
    event_id uuid not null,
    consumer_name text not null,
    processed_at timestamptz not null,
    constraint uq_processed_events_event_consumer unique (event_id, consumer_name)
);

CREATE TABLE event_processing_claims (
    event_id uuid not null,
    consumer_name text not null,
    claimed_at timestamptz not null,
    claim_expires_at timestamptz not null,
    claim_owner text not null,
    constraint uq_event_processing_claims_event_consumer unique (event_id, consumer_name)
);

CREATE TABLE snapshot_files (
    id uuid primary key default uuidv7(),
    snapshot_id uuid not null references snapshots(id),
    path text not null,
    path_hash text not null,
    parent_path text,
    name text not null,
    entry_kind text not null,
    git_mode text,
    git_blob_oid text,
    content_key text,
    content_hash text,
    size_bytes bigint,
    line_count integer,
    is_binary boolean not null,
    is_large boolean not null,
    created_at timestamptz not null
);

CREATE TABLE agent_instruction_files (
    id uuid primary key default uuidv7(),
    snapshot_id uuid not null references snapshots(id),
    path text not null,
    scope_path text not null,
    depth integer not null,
    content_hash text not null,
    content_ref text not null,
    created_at timestamptz not null
);

CREATE INDEX ix_analyses_tenant_created_at
    ON analyses (tenant_id, created_at);

CREATE INDEX ix_analyses_tenant_created_by
    ON analyses (tenant_id, created_by_user_id);

CREATE INDEX ix_analyses_tenant_user_repository_url
    ON analyses (tenant_id, created_by_user_id, repository_url text_pattern_ops);

CREATE INDEX ix_analyses_status_updated_at
    ON analyses (status, updated_at);

CREATE UNIQUE INDEX uq_tenants_slug
    ON tenants (slug);

CREATE UNIQUE INDEX uq_users_tenant_email
    ON users (tenant_id, email);

CREATE INDEX ix_users_tenant_created_at
    ON users (tenant_id, created_at);

CREATE UNIQUE INDEX uq_user_credentials_user_id
    ON user_credentials (user_id);

CREATE UNIQUE INDEX uq_oauth_accounts_provider_account
    ON oauth_accounts (provider, provider_account_id);

CREATE UNIQUE INDEX uq_oauth_accounts_provider_tenant_email
    ON oauth_accounts (provider, tenant_id, provider_email);

CREATE INDEX ix_oauth_accounts_user_provider
    ON oauth_accounts (user_id, provider);

CREATE UNIQUE INDEX uq_refresh_tokens_token_hash
    ON refresh_tokens (token_hash);

CREATE INDEX ix_refresh_tokens_user_expires_at
    ON refresh_tokens (user_id, expires_at);

CREATE UNIQUE INDEX uq_permissions_name
    ON permissions (name);

CREATE UNIQUE INDEX uq_roles_tenant_name
    ON roles (tenant_id, name);

CREATE UNIQUE INDEX uq_role_permissions_role_permission
    ON role_permissions (role_id, permission_id);

CREATE UNIQUE INDEX uq_user_roles_user_role
    ON user_roles (user_id, role_id);

CREATE INDEX ix_audit_log_tenant_created_at
    ON audit_log (tenant_id, created_at);

CREATE INDEX ix_agent_sessions_analysis_id
    ON agent_sessions (analysis_id);

CREATE INDEX ix_agent_turns_agent_turn_index
    ON agent_turns (agent_id, turn_index);

CREATE UNIQUE INDEX uq_agent_turns_agent_trigger_event
    ON agent_turns (agent_id, trigger_event_id);

CREATE UNIQUE INDEX uq_agent_turns_agent_trigger_domain
    ON agent_turns (agent_id, trigger_domain_key);

CREATE UNIQUE INDEX uq_agent_stream_events_analysis_seq
    ON agent_stream_events (analysis_id, seq);

CREATE INDEX ix_agent_stream_events_agent_seq
    ON agent_stream_events (agent_id, seq);

CREATE UNIQUE INDEX uq_agent_context_items_agent_seq
    ON agent_context_items (agent_id, seq);

CREATE UNIQUE INDEX uq_agent_context_items_agent_idempotency
    ON agent_context_items (agent_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX ix_agent_context_items_agent_compacted_seq
    ON agent_context_items (agent_id, compacted_at, seq);

CREATE INDEX ix_tool_calls_agent_status
    ON tool_calls (agent_id, status);

CREATE INDEX ix_tool_calls_claim_expires_at
    ON tool_calls (claim_expires_at);

CREATE INDEX ix_tool_calls_openai_call_id
    ON tool_calls (openai_call_id);

CREATE UNIQUE INDEX uq_tool_calls_agent_openai_call
    ON tool_calls (agent_id, openai_call_id);

CREATE INDEX ix_evidence_agent_path
    ON evidence (agent_id, path);

CREATE INDEX ix_documents_analysis_status
    ON documents (analysis_id, status);

CREATE UNIQUE INDEX uq_document_revisions_document_version
    ON document_revisions (document_id, version);

CREATE UNIQUE INDEX uq_document_revisions_tool_call
    ON document_revisions (tool_call_id);

CREATE INDEX ix_outbox_events_published_created_at
    ON outbox_events (published_at, created_at);

CREATE UNIQUE INDEX uq_snapshots_repo_commit_policy
    ON snapshots (repository_url_hash, resolved_commit_sha, snapshot_policy_hash);

CREATE UNIQUE INDEX uq_snapshot_files_snapshot_path
    ON snapshot_files (snapshot_id, path);

CREATE INDEX ix_snapshot_files_snapshot_parent
    ON snapshot_files (snapshot_id, parent_path);

CREATE INDEX ix_snapshot_files_snapshot_content_hash
    ON snapshot_files (snapshot_id, content_hash);

COMMIT;
