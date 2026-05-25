from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()


def uuid_pk() -> Column[Any]:
    return Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))


analyses = Table(
    "analyses",
    metadata,
    uuid_pk(),
    Column("tenant_id", UUID(as_uuid=True)),
    Column("created_by_user_id", UUID(as_uuid=True)),
    Column("repository_url", Text, nullable=False),
    Column("repository_url_hash", Text, nullable=False),
    Column("requested_ref", Text, nullable=False),
    Column("analysis_profile_id", UUID(as_uuid=True)),
    Column("config_snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("error_code", Text),
    Column("error_message", Text),
)
Index("ix_analyses_tenant_created_at", analyses.c.tenant_id, analyses.c.created_at)
Index("ix_analyses_tenant_created_by", analyses.c.tenant_id, analyses.c.created_by_user_id)
Index(
    "ix_analyses_tenant_user_repository_url",
    analyses.c.tenant_id,
    analyses.c.created_by_user_id,
    analyses.c.repository_url,
    postgresql_ops={"repository_url": "text_pattern_ops"},
)
Index("ix_analyses_status_updated_at", analyses.c.status, analyses.c.updated_at)


tenants = Table(
    "tenants",
    metadata,
    uuid_pk(),
    Column("slug", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("uq_tenants_slug", tenants.c.slug, unique=True)


users = Table(
    "users",
    metadata,
    uuid_pk(),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False),
    Column("email", Text, nullable=False),
    Column("display_name", Text),
    Column("is_active", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("uq_users_tenant_email", users.c.tenant_id, users.c.email, unique=True)
Index("ix_users_tenant_created_at", users.c.tenant_id, users.c.created_at)


user_credentials = Table(
    "user_credentials",
    metadata,
    uuid_pk(),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("uq_user_credentials_user_id", user_credentials.c.user_id, unique=True)


oauth_accounts = Table(
    "oauth_accounts",
    metadata,
    uuid_pk(),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("provider", Text, nullable=False),
    Column("provider_account_id", Text, nullable=False),
    Column("provider_login", Text),
    Column("provider_email", Text, nullable=False),
    Column("provider_email_verified", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index(
    "uq_oauth_accounts_provider_account", oauth_accounts.c.provider, oauth_accounts.c.provider_account_id, unique=True
)
Index(
    "uq_oauth_accounts_provider_tenant_email",
    oauth_accounts.c.provider,
    oauth_accounts.c.tenant_id,
    oauth_accounts.c.provider_email,
    unique=True,
)
Index("ix_oauth_accounts_user_provider", oauth_accounts.c.user_id, oauth_accounts.c.provider)


refresh_tokens = Table(
    "refresh_tokens",
    metadata,
    uuid_pk(),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("token_hash", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_refresh_tokens_token_hash", refresh_tokens.c.token_hash, unique=True)
Index("ix_refresh_tokens_user_expires_at", refresh_tokens.c.user_id, refresh_tokens.c.expires_at)


permissions = Table(
    "permissions",
    metadata,
    uuid_pk(),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_permissions_name", permissions.c.name, unique=True)


roles = Table(
    "roles",
    metadata,
    uuid_pk(),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("tenants.id")),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_roles_tenant_name", roles.c.tenant_id, roles.c.name, unique=True)


role_permissions = Table(
    "role_permissions",
    metadata,
    uuid_pk(),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False),
    Column("permission_id", UUID(as_uuid=True), ForeignKey("permissions.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_role_permissions_role_permission", role_permissions.c.role_id, role_permissions.c.permission_id, unique=True)


user_roles = Table(
    "user_roles",
    metadata,
    uuid_pk(),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_user_roles_user_role", user_roles.c.user_id, user_roles.c.role_id, unique=True)


audit_log = Table(
    "audit_log",
    metadata,
    uuid_pk(),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("tenants.id")),
    Column("actor_user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("action", Text, nullable=False),
    Column("resource_type", Text, nullable=False),
    Column("resource_id", UUID(as_uuid=True)),
    Column("payload_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_audit_log_tenant_created_at", audit_log.c.tenant_id, audit_log.c.created_at)


agent_sessions = Table(
    "agent_sessions",
    metadata,
    uuid_pk(),
    Column("analysis_id", UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False),
    Column("snapshot_id", UUID(as_uuid=True)),
    Column("parent_agent_id", UUID(as_uuid=True)),
    Column("config_snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("goal_ref", Text, nullable=False),
    Column("effective_model", Text, nullable=False),
    Column("effective_prompt_version", Text, nullable=False),
    Column("effective_tool_registry_version", Text, nullable=False),
    Column("effective_limits_json", JSONB, nullable=False),
    Column("effective_runtime_json", JSONB, nullable=False),
    Column("latest_response_id", Text),
    Column("turn_count", Integer, nullable=False),
    Column("max_turns", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ix_agent_sessions_analysis_id", agent_sessions.c.analysis_id)


agent_turns = Table(
    "agent_turns",
    metadata,
    uuid_pk(),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("turn_index", Integer, nullable=False),
    Column("trigger_event_id", UUID(as_uuid=True)),
    Column("trigger_domain_key", Text),
    Column("status", Text, nullable=False),
    Column("response_id", Text),
    Column("previous_response_id", Text),
    Column("input_ref", Text),
    Column("output_ref", Text),
    Column("input_token_count", Integer),
    Column("output_token_count", Integer),
    Column("total_token_count", Integer),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
)
Index("ix_agent_turns_agent_turn_index", agent_turns.c.agent_id, agent_turns.c.turn_index)
Index("uq_agent_turns_agent_trigger_event", agent_turns.c.agent_id, agent_turns.c.trigger_event_id, unique=True)
Index("uq_agent_turns_agent_trigger_domain", agent_turns.c.agent_id, agent_turns.c.trigger_domain_key, unique=True)


agent_stream_events = Table(
    "agent_stream_events",
    metadata,
    uuid_pk(),
    Column("analysis_id", UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("turn_id", UUID(as_uuid=True), ForeignKey("agent_turns.id")),
    Column("seq", BigInteger, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("payload_json", JSONB, nullable=False),
    Column("attempt", Integer),
    Column("response_id", Text),
    Column("state", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_agent_stream_events_analysis_seq", agent_stream_events.c.analysis_id, agent_stream_events.c.seq, unique=True)
Index("ix_agent_stream_events_agent_seq", agent_stream_events.c.agent_id, agent_stream_events.c.seq)


agent_context_items = Table(
    "agent_context_items",
    metadata,
    uuid_pk(),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("turn_id", UUID(as_uuid=True), ForeignKey("agent_turns.id")),
    Column("seq", BigInteger, nullable=False),
    Column("item_type", Text, nullable=False),
    Column("payload_json", JSONB, nullable=False),
    Column("response_id", Text),
    Column("source", Text, nullable=False),
    Column("idempotency_key", Text),
    Column("compacted_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_agent_context_items_agent_seq", agent_context_items.c.agent_id, agent_context_items.c.seq, unique=True)
Index(
    "uq_agent_context_items_agent_idempotency",
    agent_context_items.c.agent_id,
    agent_context_items.c.idempotency_key,
    unique=True,
    postgresql_where=agent_context_items.c.idempotency_key.isnot(None),
)
Index(
    "ix_agent_context_items_agent_compacted_seq",
    agent_context_items.c.agent_id,
    agent_context_items.c.compacted_at,
    agent_context_items.c.seq,
)


agent_todo_lists = Table(
    "agent_todo_lists",
    metadata,
    uuid_pk(),
    Column("analysis_id", UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("turn_id", UUID(as_uuid=True), ForeignKey("agent_turns.id")),
    Column("tool_call_id", UUID(as_uuid=True), ForeignKey("tool_calls.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("items_json", JSONB, nullable=False),
    Column("note", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_agent_todo_lists_agent_version", agent_todo_lists.c.agent_id, agent_todo_lists.c.version, unique=True)
Index("uq_agent_todo_lists_tool_call", agent_todo_lists.c.tool_call_id, unique=True)
Index("ix_agent_todo_lists_analysis_version", agent_todo_lists.c.analysis_id, agent_todo_lists.c.version)


context_assemblies = Table(
    "context_assemblies",
    metadata,
    uuid_pk(),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("turn_id", UUID(as_uuid=True), ForeignKey("agent_turns.id"), nullable=False),
    Column("config_snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("source_refs_json", JSONB, nullable=False),
    Column("input_ref", Text, nullable=False),
    Column("instructions_hash", Text, nullable=False),
    Column("tool_schema_hash", Text, nullable=False),
    Column("token_estimate", Integer),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


tool_calls = Table(
    "tool_calls",
    metadata,
    uuid_pk(),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("turn_id", UUID(as_uuid=True), ForeignKey("agent_turns.id"), nullable=False),
    Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("openai_call_id", Text, nullable=False),
    Column("tool_name", Text, nullable=False),
    Column("arguments_json", JSONB, nullable=False),
    Column("tool_registry_version", Text, nullable=False),
    Column("tool_schema_hash", Text, nullable=False),
    Column("tool_policy_hash", Text, nullable=False),
    Column("permission_decision", Text),
    Column("status", Text, nullable=False),
    Column("result_ref", Text),
    Column("result_summary", Text),
    Column("duration_ms", Integer),
    Column("error_code", Text),
    Column("error_message", Text),
    Column("claimed_at", DateTime(timezone=True)),
    Column("claim_expires_at", DateTime(timezone=True)),
    Column("claim_owner", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
)
Index("ix_tool_calls_agent_status", tool_calls.c.agent_id, tool_calls.c.status)
Index("ix_tool_calls_claim_expires_at", tool_calls.c.claim_expires_at)
Index("ix_tool_calls_openai_call_id", tool_calls.c.openai_call_id)
Index("uq_tool_calls_agent_openai_call", tool_calls.c.agent_id, tool_calls.c.openai_call_id, unique=True)


evidence = Table(
    "evidence",
    metadata,
    uuid_pk(),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("tool_call_id", UUID(as_uuid=True), ForeignKey("tool_calls.id")),
    Column("path", Text, nullable=False),
    Column("start_line", Integer),
    Column("end_line", Integer),
    Column("content_hash", Text),
    Column("snippet_ref", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_evidence_agent_path", evidence.c.agent_id, evidence.c.path)


documents = Table(
    "documents",
    metadata,
    uuid_pk(),
    Column("analysis_id", UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("title", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("current_version", Integer, nullable=False),
    Column("content_ref", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("finalized_at", DateTime(timezone=True)),
)
Index("ix_documents_analysis_status", documents.c.analysis_id, documents.c.status)


document_nodes = Table(
    "document_nodes",
    metadata,
    uuid_pk(),
    Column("analysis_id", UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("parent_id", UUID(as_uuid=True), ForeignKey("document_nodes.id")),
    Column("node_type", Text, nullable=False),
    Column("document_id", UUID(as_uuid=True), ForeignKey("documents.id")),
    Column("title", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("path", Text, nullable=False),
    Column("focus_area", Text),
    Column("sort_order", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index(
    "uq_document_nodes_analysis_parent_slug",
    document_nodes.c.analysis_id,
    document_nodes.c.parent_id,
    document_nodes.c.slug,
    unique=True,
)
Index("uq_document_nodes_document_id", document_nodes.c.document_id, unique=True)
Index("ix_document_nodes_analysis_parent_sort", document_nodes.c.analysis_id, document_nodes.c.parent_id, document_nodes.c.sort_order)


document_revisions = Table(
    "document_revisions",
    metadata,
    uuid_pk(),
    Column("document_id", UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("tool_call_id", UUID(as_uuid=True), ForeignKey("tool_calls.id"), nullable=False),
    Column("operation", Text, nullable=False),
    Column("content_ref", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index(
    "uq_document_revisions_document_version",
    document_revisions.c.document_id,
    document_revisions.c.version,
    unique=True,
)
Index("uq_document_revisions_tool_call", document_revisions.c.tool_call_id, unique=True)


document_sections = Table(
    "document_sections",
    metadata,
    uuid_pk(),
    Column("document_id", UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False),
    Column("stable_id", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("sort_order", Integer, nullable=False),
    Column("content_ref", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("uq_document_sections_document_stable_id", document_sections.c.document_id, document_sections.c.stable_id, unique=True)
Index("ix_document_sections_document_sort", document_sections.c.document_id, document_sections.c.sort_order)


document_section_revisions = Table(
    "document_section_revisions",
    metadata,
    uuid_pk(),
    Column("section_id", UUID(as_uuid=True), ForeignKey("document_sections.id"), nullable=False),
    Column("document_id", UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False),
    Column("document_revision_id", UUID(as_uuid=True), ForeignKey("document_revisions.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("title", Text, nullable=False),
    Column("sort_order", Integer, nullable=False),
    Column("content_ref", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index(
    "uq_document_section_revisions_section_version",
    document_section_revisions.c.section_id,
    document_section_revisions.c.version,
    unique=True,
)


memory_summaries = Table(
    "memory_summaries",
    metadata,
    uuid_pk(),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agent_sessions.id"), nullable=False),
    Column("compacted_until_turn", Integer, nullable=False),
    Column("summary_json", JSONB, nullable=False),
    Column("evidence_ids_json", JSONB, nullable=False),
    Column("focus_paths_json", JSONB, nullable=False),
    Column("next_action", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


config_snapshots = Table(
    "config_snapshots",
    metadata,
    uuid_pk(),
    Column("config_version", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("config_json", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


outbox_events = Table(
    "outbox_events",
    metadata,
    uuid_pk(),
    Column("event_type", Text, nullable=False),
    Column("payload_json", JSONB, nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_outbox_events_published_created_at", outbox_events.c.published_at, outbox_events.c.created_at)


processed_events = Table(
    "processed_events",
    metadata,
    Column("event_id", UUID(as_uuid=True), nullable=False),
    Column("consumer_name", Text, nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("event_id", "consumer_name", name="uq_processed_events_event_consumer"),
)


event_processing_claims = Table(
    "event_processing_claims",
    metadata,
    Column("event_id", UUID(as_uuid=True), nullable=False),
    Column("consumer_name", Text, nullable=False),
    Column("claimed_at", DateTime(timezone=True), nullable=False),
    Column("claim_expires_at", DateTime(timezone=True), nullable=False),
    Column("claim_owner", Text, nullable=False),
    UniqueConstraint("event_id", "consumer_name", name="uq_event_processing_claims_event_consumer"),
)


snapshots = Table(
    "snapshots",
    metadata,
    uuid_pk(),
    Column("tenant_id", UUID(as_uuid=True)),
    Column("repository_url_hash", Text, nullable=False),
    Column("requested_ref", Text, nullable=False),
    Column("resolved_commit_sha", Text, nullable=False),
    Column("tree_sha", Text, nullable=False),
    Column("snapshot_policy_hash", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("manifest_key", Text),
    Column("git_bundle_key", Text),
    Column("file_count", Integer),
    Column("total_bytes", BigInteger),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("ready_at", DateTime(timezone=True)),
    Column("error_code", Text),
    Column("error_message", Text),
)
Index(
    "uq_snapshots_repo_commit_policy",
    snapshots.c.repository_url_hash,
    snapshots.c.resolved_commit_sha,
    snapshots.c.snapshot_policy_hash,
    unique=True,
)


snapshot_files = Table(
    "snapshot_files",
    metadata,
    uuid_pk(),
    Column("snapshot_id", UUID(as_uuid=True), ForeignKey("snapshots.id"), nullable=False),
    Column("path", Text, nullable=False),
    Column("path_hash", Text, nullable=False),
    Column("parent_path", Text),
    Column("name", Text, nullable=False),
    Column("entry_kind", Text, nullable=False),
    Column("git_mode", Text),
    Column("git_blob_oid", Text),
    Column("content_key", Text),
    Column("content_hash", Text),
    Column("size_bytes", BigInteger),
    Column("line_count", Integer),
    Column("is_binary", Boolean, nullable=False),
    Column("is_large", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("uq_snapshot_files_snapshot_path", snapshot_files.c.snapshot_id, snapshot_files.c.path, unique=True)
Index("ix_snapshot_files_snapshot_parent", snapshot_files.c.snapshot_id, snapshot_files.c.parent_path)
Index("ix_snapshot_files_snapshot_content_hash", snapshot_files.c.snapshot_id, snapshot_files.c.content_hash)


agent_instruction_files = Table(
    "agent_instruction_files",
    metadata,
    uuid_pk(),
    Column("snapshot_id", UUID(as_uuid=True), ForeignKey("snapshots.id"), nullable=False),
    Column("path", Text, nullable=False),
    Column("scope_path", Text, nullable=False),
    Column("depth", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("content_ref", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
