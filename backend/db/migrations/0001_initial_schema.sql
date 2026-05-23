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

CREATE INDEX ix_analyses_status_updated_at
    ON analyses (status, updated_at);

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
