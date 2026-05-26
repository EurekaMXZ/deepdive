from __future__ import annotations

import unittest

from backend.db.schema import metadata
from sqlalchemy.dialects.postgresql import JSONB, UUID


class DatabaseSchemaTest(unittest.TestCase):
    def test_core_tables_exist(self) -> None:
        required_tables = {
            "analyses",
            "tenants",
            "users",
            "user_credentials",
            "oauth_accounts",
            "refresh_tokens",
            "roles",
            "permissions",
            "role_permissions",
            "user_roles",
            "audit_log",
            "agent_sessions",
            "agent_turns",
            "agent_context_items",
            "agent_todo_lists",
            "agent_stream_events",
            "context_assemblies",
            "tool_calls",
            "evidence",
            "memory_summaries",
            "analysis_repositories",
            "analysis_batches",
            "analysis_batch_items",
            "config_snapshots",
            "outbox_events",
            "processed_events",
            "event_processing_claims",
            "snapshots",
            "snapshot_files",
            "agent_instruction_files",
            "documents",
            "document_nodes",
            "document_sections",
            "document_section_revisions",
            "document_revisions",
        }

        self.assertTrue(required_tables.issubset(metadata.tables.keys()))

    def test_uuid_primary_keys_use_postgres_uuidv7_default(self) -> None:
        for table_name, table in metadata.tables.items():
            if table_name in {"processed_events", "event_processing_claims"}:
                continue
            with self.subTest(table=table_name):
                id_column = table.c.id
                self.assertTrue(id_column.primary_key)
                self.assertIsInstance(id_column.type, UUID)
                self.assertEqual(str(id_column.server_default.arg), "uuidv7()")

    def test_json_payload_columns_use_jsonb(self) -> None:
        json_columns = [
            metadata.tables["config_snapshots"].c.config_json,
            metadata.tables["outbox_events"].c.payload_json,
            metadata.tables["agent_stream_events"].c.payload_json,
            metadata.tables["agent_context_items"].c.payload_json,
            metadata.tables["agent_todo_lists"].c.items_json,
            metadata.tables["tool_calls"].c.arguments_json,
            metadata.tables["memory_summaries"].c.summary_json,
            metadata.tables["agent_sessions"].c.effective_limits_json,
        ]

        for column in json_columns:
            with self.subTest(column=str(column)):
                self.assertIsInstance(column.type, JSONB)

    def test_idempotency_and_stream_replay_constraints_exist(self) -> None:
        processed = metadata.tables["processed_events"]
        claims = metadata.tables["event_processing_claims"]
        stream = metadata.tables["agent_stream_events"]
        context_items = metadata.tables["agent_context_items"]
        todo_lists = metadata.tables["agent_todo_lists"]
        turns = metadata.tables["agent_turns"]
        tool_calls = metadata.tables["tool_calls"]
        snapshots = metadata.tables["snapshots"]
        snapshot_files = metadata.tables["snapshot_files"]
        document_revisions = metadata.tables["document_revisions"]
        document_nodes = metadata.tables["document_nodes"]
        document_sections = metadata.tables["document_sections"]
        document_section_revisions = metadata.tables["document_section_revisions"]
        users = metadata.tables["users"]
        refresh_tokens = metadata.tables["refresh_tokens"]
        roles = metadata.tables["roles"]
        permissions = metadata.tables["permissions"]
        role_permissions = metadata.tables["role_permissions"]
        user_roles = metadata.tables["user_roles"]
        oauth_accounts = metadata.tables["oauth_accounts"]
        analysis_repositories = metadata.tables["analysis_repositories"]
        analysis_batches = metadata.tables["analysis_batches"]
        analysis_batch_items = metadata.tables["analysis_batch_items"]

        self.assertIn("created_by_user_id", metadata.tables["analyses"].c)
        self.assertIn(
            ("tenant_id", "created_by_user_id", "repository_url"),
            {_columns(index) for index in metadata.tables["analyses"].indexes},
        )
        self.assertIn(
            ("tenant_id", "email"),
            {_columns(index) for index in users.indexes if index.unique},
        )
        self.assertIn(
            ("token_hash",),
            {_columns(index) for index in refresh_tokens.indexes if index.unique},
        )
        self.assertIn(
            ("tenant_id", "name"),
            {_columns(index) for index in roles.indexes if index.unique},
        )
        self.assertIn(
            ("name",),
            {_columns(index) for index in permissions.indexes if index.unique},
        )
        self.assertIn(
            ("role_id", "permission_id"),
            {_columns(index) for index in role_permissions.indexes if index.unique},
        )
        self.assertIn(
            ("user_id", "role_id"),
            {_columns(index) for index in user_roles.indexes if index.unique},
        )
        self.assertIn(
            ("provider", "provider_account_id"),
            {_columns(index) for index in oauth_accounts.indexes if index.unique},
        )
        self.assertIn(
            ("provider", "tenant_id", "provider_email"),
            {_columns(index) for index in oauth_accounts.indexes if index.unique},
        )
        self.assertIn(
            ("tenant_id", "created_by_user_id", "repository_url_hash"),
            {_columns(index) for index in analysis_repositories.indexes if index.unique},
        )
        self.assertIn(
            ("tenant_id", "created_by_user_id", "last_analyzed_at"),
            {_columns(index) for index in analysis_repositories.indexes},
        )
        self.assertIn("max_parallel", analysis_batches.c)
        self.assertIn("pending_count", analysis_batches.c)
        self.assertIn("active_count", analysis_batches.c)
        self.assertIn("completed_count", analysis_batches.c)
        self.assertIn("failed_count", analysis_batches.c)
        self.assertIn("cancelled_count", analysis_batches.c)
        self.assertIn(
            ("tenant_id", "created_by_user_id", "created_at"),
            {_columns(index) for index in analysis_batches.indexes},
        )
        self.assertIn("status", analysis_batch_items.c)
        self.assertIn("sort_order", analysis_batch_items.c)
        self.assertIn("dispatched_at", analysis_batch_items.c)
        self.assertIn("dispatch_owner", analysis_batch_items.c)
        self.assertIn(
            ("batch_id", "status", "sort_order"),
            {_columns(index) for index in analysis_batch_items.indexes},
        )
        self.assertIn(
            ("analysis_id",),
            {_columns(index) for index in analysis_batch_items.indexes if index.unique},
        )
        self.assertIn(
            ("event_id", "consumer_name"),
            {_columns(constraint) for constraint in processed.constraints},
        )
        self.assertIn(
            ("event_id", "consumer_name"),
            {_columns(constraint) for constraint in claims.constraints},
        )
        self.assertIn("claim_expires_at", claims.c)
        self.assertIn("claim_owner", claims.c)
        self.assertIn(
            ("analysis_id", "seq"),
            {_columns(index) for index in stream.indexes if index.unique},
        )
        self.assertIn("turn_id", stream.c)
        self.assertIn("attempt", stream.c)
        self.assertIn("response_id", stream.c)
        self.assertIn("state", stream.c)
        self.assertIn("idempotency_key", stream.c)
        self.assertIn(
            ("agent_id", "idempotency_key"),
            {_columns(index) for index in stream.indexes if index.unique},
        )
        self.assertIn("seq", context_items.c)
        self.assertIn("item_type", context_items.c)
        self.assertIn("payload_json", context_items.c)
        self.assertIn("idempotency_key", context_items.c)
        self.assertIn("compacted_at", context_items.c)
        self.assertIn(
            ("agent_id", "seq"),
            {_columns(index) for index in context_items.indexes if index.unique},
        )
        self.assertIn(
            ("agent_id", "idempotency_key"),
            {_columns(index) for index in context_items.indexes if index.unique},
        )
        self.assertIn(
            ("agent_id", "compacted_at", "seq"),
            {_columns(index) for index in context_items.indexes},
        )
        self.assertIn(
            ("agent_id", "version"),
            {_columns(index) for index in todo_lists.indexes if index.unique},
        )
        self.assertIn(
            ("tool_call_id",),
            {_columns(index) for index in todo_lists.indexes if index.unique},
        )
        self.assertIn(
            ("analysis_id", "version"),
            {_columns(index) for index in todo_lists.indexes},
        )
        self.assertIn(
            ("agent_id", "trigger_event_id"),
            {_columns(index) for index in turns.indexes if index.unique},
        )
        self.assertIn("trigger_domain_key", turns.c)
        self.assertIn("cached_input_token_count", turns.c)
        self.assertIn("uncached_input_token_count", turns.c)
        self.assertIn("reasoning_token_count", turns.c)
        self.assertIn(
            ("agent_id", "trigger_domain_key"),
            {_columns(index) for index in turns.indexes if index.unique},
        )
        self.assertIn(
            ("agent_id", "openai_call_id"),
            {_columns(index) for index in tool_calls.indexes if index.unique},
        )
        self.assertIn("claimed_at", tool_calls.c)
        self.assertIn("claim_expires_at", tool_calls.c)
        self.assertIn("claim_owner", tool_calls.c)
        self.assertIn(
            ("claim_expires_at",),
            {_columns(index) for index in tool_calls.indexes},
        )
        self.assertIn(
            ("snapshot_id", "path"),
            {_columns(index) for index in snapshot_files.indexes if index.unique},
        )
        self.assertIn(
            ("repository_url_hash", "resolved_commit_sha", "snapshot_policy_hash"),
            {_columns(index) for index in snapshots.indexes if index.unique},
        )
        self.assertIn(
            ("document_id", "version"),
            {_columns(index) for index in document_revisions.indexes if index.unique},
        )
        self.assertIn(
            ("tool_call_id",),
            {_columns(index) for index in document_revisions.indexes if index.unique},
        )
        self.assertIn(
            ("analysis_id", "parent_id", "slug"),
            {_columns(index) for index in document_nodes.indexes if index.unique},
        )
        self.assertIn(
            ("document_id",),
            {_columns(index) for index in document_nodes.indexes if index.unique},
        )
        self.assertIn(
            ("document_id", "stable_id"),
            {_columns(index) for index in document_sections.indexes if index.unique},
        )
        self.assertIn(
            ("section_id", "version"),
            {_columns(index) for index in document_section_revisions.indexes if index.unique},
        )

    def test_agent_todo_lists_have_expected_columns(self) -> None:
        todo_lists = metadata.tables["agent_todo_lists"]

        for column_name in [
            "analysis_id",
            "agent_id",
            "turn_id",
            "tool_call_id",
            "version",
            "items_json",
            "note",
            "created_at",
        ]:
            with self.subTest(table="agent_todo_lists", column=column_name):
                self.assertIn(column_name, todo_lists.c)

    def test_document_tables_have_expected_columns(self) -> None:
        documents = metadata.tables["documents"]
        revisions = metadata.tables["document_revisions"]
        nodes = metadata.tables["document_nodes"]
        sections = metadata.tables["document_sections"]
        section_revisions = metadata.tables["document_section_revisions"]

        for column_name in [
            "analysis_id",
            "agent_id",
            "title",
            "kind",
            "status",
            "current_version",
            "content_ref",
            "content_hash",
            "size_bytes",
            "created_at",
            "updated_at",
            "finalized_at",
        ]:
            with self.subTest(table="documents", column=column_name):
                self.assertIn(column_name, documents.c)

        for column_name in [
            "document_id",
            "version",
            "tool_call_id",
            "operation",
            "content_ref",
            "content_hash",
            "size_bytes",
            "created_at",
        ]:
            with self.subTest(table="document_revisions", column=column_name):
                self.assertIn(column_name, revisions.c)

        for column_name in [
            "analysis_id",
            "agent_id",
            "parent_id",
            "node_type",
            "document_id",
            "title",
            "slug",
            "path",
            "focus_area",
            "sort_order",
            "created_at",
            "updated_at",
        ]:
            with self.subTest(table="document_nodes", column=column_name):
                self.assertIn(column_name, nodes.c)

        for column_name in [
            "document_id",
            "stable_id",
            "title",
            "sort_order",
            "content_ref",
            "content_hash",
            "size_bytes",
            "created_at",
            "updated_at",
        ]:
            with self.subTest(table="document_sections", column=column_name):
                self.assertIn(column_name, sections.c)

        for column_name in [
            "section_id",
            "document_id",
            "document_revision_id",
            "version",
            "title",
            "sort_order",
            "content_ref",
            "content_hash",
            "size_bytes",
            "created_at",
        ]:
            with self.subTest(table="document_section_revisions", column=column_name):
                self.assertIn(column_name, section_revisions.c)

    def test_analysis_repositories_have_expected_columns(self) -> None:
        repositories = metadata.tables["analysis_repositories"]

        for column_name in [
            "tenant_id",
            "created_by_user_id",
            "repository_url",
            "repository_url_hash",
            "repository_host",
            "repository_owner",
            "repository_name",
            "repository_label",
            "search_text",
            "latest_analysis_id",
            "latest_status",
            "latest_requested_ref",
            "latest_resolved_commit_sha",
            "analysis_count",
            "completed_analysis_count",
            "last_analyzed_at",
            "created_at",
            "updated_at",
        ]:
            with self.subTest(table="analysis_repositories", column=column_name):
                self.assertIn(column_name, repositories.c)

    def test_agent_session_uses_limits_not_budget_naming(self) -> None:
        columns = metadata.tables["agent_sessions"].c

        self.assertIn("effective_limits_json", columns)
        self.assertNotIn("effective_budget_json", columns)


def _columns(schema_item: object) -> tuple[str, ...]:
    return tuple(column.name for column in schema_item.columns)


if __name__ == "__main__":
    unittest.main()
