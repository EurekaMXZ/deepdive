from __future__ import annotations

import re
import unittest
from pathlib import Path

from backend.db.schema import metadata

MIGRATION_PATH = Path("backend/db/migrations/0001_initial_schema.sql")


class DatabaseMigrationTest(unittest.TestCase):
    def test_initial_migration_creates_all_schema_tables(self) -> None:
        sql = _migration_sql()

        for table_name in metadata.tables:
            with self.subTest(table=table_name):
                self.assertRegex(sql, rf"\bcreate\s+table\s+{table_name}\b")

    def test_uuid_primary_key_tables_use_postgres_uuidv7_default(self) -> None:
        sql = _migration_sql()

        for table_name in metadata.tables:
            if table_name in {"processed_events", "event_processing_claims"}:
                continue
            with self.subTest(table=table_name):
                body = _create_table_body(sql, table_name)
                self.assertRegex(body, r"\bid\s+uuid\s+primary\s+key\s+default\s+uuidv7\(\)")

    def test_json_payload_columns_use_jsonb(self) -> None:
        sql = _migration_sql()
        required_jsonb_columns = {
            "agent_sessions": [
                "effective_limits_json",
                "effective_runtime_json",
            ],
            "agent_stream_events": ["payload_json"],
            "agent_context_items": ["payload_json"],
            "agent_todo_lists": ["items_json"],
            "context_assemblies": ["source_refs_json"],
            "tool_calls": ["arguments_json"],
            "memory_summaries": [
                "summary_json",
                "evidence_ids_json",
                "focus_paths_json",
            ],
            "config_snapshots": ["config_json"],
            "outbox_events": ["payload_json"],
        }

        for table_name, column_names in required_jsonb_columns.items():
            body = _create_table_body(sql, table_name)
            for column_name in column_names:
                with self.subTest(table=table_name, column=column_name):
                    self.assertRegex(body, rf"\b{column_name}\s+jsonb\b")

    def test_migration_creates_referenced_tables_before_dependents(self) -> None:
        sql = _migration_sql()
        required_order = [
            ("tenants", "users"),
            ("users", "user_credentials"),
            ("tenants", "analysis_repositories"),
            ("users", "analysis_repositories"),
            ("analyses", "analysis_repositories"),
            ("agent_sessions", "agent_turns"),
            ("agent_sessions", "agent_stream_events"),
            ("agent_turns", "agent_stream_events"),
            ("agent_sessions", "agent_context_items"),
            ("agent_turns", "agent_context_items"),
            ("agent_sessions", "agent_context_windows"),
            ("agent_turns", "agent_context_windows"),
            ("agent_sessions", "tool_calls"),
            ("agent_turns", "tool_calls"),
            ("analyses", "agent_todo_lists"),
            ("agent_sessions", "agent_todo_lists"),
            ("agent_turns", "agent_todo_lists"),
            ("tool_calls", "agent_todo_lists"),
            ("agent_sessions", "context_assemblies"),
            ("agent_turns", "context_assemblies"),
            ("agent_sessions", "evidence"),
            ("tool_calls", "evidence"),
            ("analyses", "documents"),
            ("agent_sessions", "documents"),
            ("documents", "document_nodes"),
            ("documents", "document_revisions"),
            ("tool_calls", "document_revisions"),
            ("documents", "document_sections"),
            ("documents", "document_section_revisions"),
            ("document_sections", "document_section_revisions"),
            ("document_revisions", "document_section_revisions"),
        ]

        for referenced, dependent in required_order:
            with self.subTest(referenced=referenced, dependent=dependent):
                self.assertLess(_create_table_position(sql, referenced), _create_table_position(sql, dependent))

    def test_migration_defines_replay_idempotency_and_snapshot_constraints(self) -> None:
        sql = _migration_sql()

        self.assertRegex(
            sql,
            r"constraint\s+uq_processed_events_event_consumer\s+unique\s+\(event_id,\s*consumer_name\)",
        )
        self.assertRegex(
            sql,
            r"constraint\s+uq_event_processing_claims_event_consumer\s+unique\s+\(event_id,\s*consumer_name\)",
        )
        self.assertRegex(
            _create_table_body(sql, "event_processing_claims"), r"\bclaim_expires_at\s+timestamptz\s+not\s+null\b"
        )
        self.assertRegex(_create_table_body(sql, "event_processing_claims"), r"\bclaim_owner\s+text\s+not\s+null\b")
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_agent_stream_events_analysis_seq\s+on\s+agent_stream_events"
            r"\s+\(analysis_id,\s*seq\)",
        )
        stream_body = _create_table_body(sql, "agent_stream_events")
        self.assertRegex(stream_body, r"\bturn_id\s+uuid\b")
        self.assertRegex(stream_body, r"\battempt\s+integer\b")
        self.assertRegex(stream_body, r"\bresponse_id\s+text\b")
        self.assertRegex(stream_body, r"\bstate\s+text\b")
        context_items_body = _create_table_body(sql, "agent_context_items")
        self.assertRegex(context_items_body, r"\bseq\s+bigint\s+not\s+null\b")
        self.assertRegex(context_items_body, r"\bitem_type\s+text\s+not\s+null\b")
        self.assertRegex(context_items_body, r"\bpayload_json\s+jsonb\s+not\s+null\b")
        self.assertRegex(context_items_body, r"\bidempotency_key\s+text\b")
        self.assertRegex(context_items_body, r"\bcompacted_at\s+timestamptz\b")
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_agent_context_items_agent_seq\s+on\s+agent_context_items"
            r"\s+\(agent_id,\s*seq\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_agent_context_items_agent_idempotency\s+on\s+agent_context_items"
            r"\s+\(agent_id,\s*idempotency_key\)",
        )
        todo_lists_body = _create_table_body(sql, "agent_todo_lists")
        self.assertRegex(todo_lists_body, r"\banalysis_id\s+uuid\s+not\s+null\b")
        self.assertRegex(todo_lists_body, r"\bagent_id\s+uuid\s+not\s+null\b")
        self.assertRegex(todo_lists_body, r"\bturn_id\s+uuid\b")
        self.assertRegex(todo_lists_body, r"\btool_call_id\s+uuid\s+not\s+null\b")
        self.assertRegex(todo_lists_body, r"\bversion\s+integer\s+not\s+null\b")
        self.assertRegex(todo_lists_body, r"\bitems_json\s+jsonb\s+not\s+null\b")
        self.assertRegex(todo_lists_body, r"\bnote\s+text\b")
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_agent_todo_lists_agent_version\s+on\s+agent_todo_lists"
            r"\s+\(agent_id,\s*version\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_agent_todo_lists_tool_call\s+on\s+agent_todo_lists"
            r"\s+\(tool_call_id\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_agent_turns_agent_trigger_event\s+on\s+agent_turns"
            r"\s+\(agent_id,\s*trigger_event_id\)",
        )
        self.assertRegex(_create_table_body(sql, "agent_turns"), r"\btrigger_domain_key\s+text\b")
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_agent_turns_agent_trigger_domain\s+on\s+agent_turns"
            r"\s+\(agent_id,\s*trigger_domain_key\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_tool_calls_agent_openai_call\s+on\s+tool_calls"
            r"\s+\(agent_id,\s*openai_call_id\)",
        )
        tool_calls_body = _create_table_body(sql, "tool_calls")
        self.assertRegex(tool_calls_body, r"\bclaimed_at\s+timestamptz\b")
        self.assertRegex(tool_calls_body, r"\bclaim_expires_at\s+timestamptz\b")
        self.assertRegex(tool_calls_body, r"\bclaim_owner\s+text\b")
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_snapshot_files_snapshot_path\s+on\s+snapshot_files"
            r"\s+\(snapshot_id,\s*path\)",
        )
        analyses_body = _create_table_body(sql, "analyses")
        analysis_repositories_body = _create_table_body(sql, "analysis_repositories")
        self.assertRegex(analyses_body, r"\bcreated_by_user_id\s+uuid\b")
        self.assertRegex(analysis_repositories_body, r"\brepository_label\s+text\s+not\s+null\b")
        self.assertRegex(analysis_repositories_body, r"\bsearch_text\s+text\s+not\s+null\b")
        self.assertRegex(analysis_repositories_body, r"\blatest_analysis_id\s+uuid\s+not\s+null\b")
        self.assertRegex(analysis_repositories_body, r"\banalysis_count\s+integer\s+not\s+null\b")
        self.assertRegex(analysis_repositories_body, r"\bcompleted_analysis_count\s+integer\s+not\s+null\b")
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_users_tenant_email\s+on\s+users\s+\(tenant_id,\s*email\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_refresh_tokens_token_hash\s+on\s+refresh_tokens\s+\(token_hash\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_roles_tenant_name\s+on\s+roles\s+\(tenant_id,\s*name\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_role_permissions_role_permission\s+on\s+role_permissions"
            r"\s+\(role_id,\s*permission_id\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_user_roles_user_role\s+on\s+user_roles\s+\(user_id,\s*role_id\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_oauth_accounts_provider_account\s+on\s+oauth_accounts"
            r"\s+\(provider,\s*provider_account_id\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_oauth_accounts_provider_tenant_email\s+on\s+oauth_accounts"
            r"\s+\(provider,\s*tenant_id,\s*provider_email\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_snapshots_repo_commit_policy\s+on\s+snapshots"
            r"\s+\(repository_url_hash,\s*resolved_commit_sha,\s*snapshot_policy_hash\)",
        )
        documents_body = _create_table_body(sql, "documents")
        document_revisions_body = _create_table_body(sql, "document_revisions")
        document_nodes_body = _create_table_body(sql, "document_nodes")
        document_sections_body = _create_table_body(sql, "document_sections")
        document_section_revisions_body = _create_table_body(sql, "document_section_revisions")
        self.assertRegex(documents_body, r"\banalysis_id\s+uuid\s+not\s+null\b")
        self.assertRegex(documents_body, r"\bagent_id\s+uuid\s+not\s+null\b")
        self.assertRegex(documents_body, r"\bstatus\s+text\s+not\s+null\b")
        self.assertRegex(documents_body, r"\bcurrent_version\s+integer\s+not\s+null\b")
        self.assertRegex(document_revisions_body, r"\btool_call_id\s+uuid\s+not\s+null\b")
        self.assertRegex(document_nodes_body, r"\bparent_id\s+uuid\b")
        self.assertRegex(document_nodes_body, r"\bnode_type\s+text\s+not\s+null\b")
        self.assertRegex(document_nodes_body, r"\bdocument_id\s+uuid\b")
        self.assertRegex(document_nodes_body, r"\bfocus_area\s+text\b")
        self.assertRegex(document_sections_body, r"\bdocument_id\s+uuid\s+not\s+null\b")
        self.assertRegex(document_sections_body, r"\bstable_id\s+text\s+not\s+null\b")
        self.assertRegex(document_sections_body, r"\bsort_order\s+integer\s+not\s+null\b")
        self.assertRegex(document_section_revisions_body, r"\bsection_id\s+uuid\s+not\s+null\b")
        self.assertRegex(document_section_revisions_body, r"\bdocument_revision_id\s+uuid\s+not\s+null\b")
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_document_revisions_document_version\s+on\s+document_revisions"
            r"\s+\(document_id,\s*version\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_document_revisions_tool_call\s+on\s+document_revisions"
            r"\s+\(tool_call_id\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_document_nodes_analysis_parent_slug\s+on\s+document_nodes"
            r"\s+\(analysis_id,\s*parent_id,\s*slug\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_document_sections_document_stable_id\s+on\s+document_sections"
            r"\s+\(document_id,\s*stable_id\)",
        )
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_document_section_revisions_section_version"
            r"\s+on\s+document_section_revisions\s+\(section_id,\s*version\)",
        )

    def test_migration_defines_query_path_indexes(self) -> None:
        sql = _migration_sql()
        required_indexes = {
            "ix_analyses_tenant_created_at": "analyses",
            "ix_analyses_tenant_created_by": "analyses",
            "ix_analyses_tenant_user_repository_url": "analyses",
            "ix_analyses_status_updated_at": "analyses",
            "ix_analysis_repositories_scope_recent": "analysis_repositories",
            "ix_analysis_repositories_label_trgm": "analysis_repositories",
            "ix_analysis_repositories_text_trgm": "analysis_repositories",
            "ix_users_tenant_created_at": "users",
            "ix_refresh_tokens_user_expires_at": "refresh_tokens",
            "ix_audit_log_tenant_created_at": "audit_log",
            "ix_agent_sessions_analysis_id": "agent_sessions",
            "ix_agent_turns_agent_turn_index": "agent_turns",
            "ix_agent_context_items_agent_compacted_seq": "agent_context_items",
            "ix_agent_todo_lists_analysis_version": "agent_todo_lists",
            "ix_agent_stream_events_agent_seq": "agent_stream_events",
            "ix_document_nodes_analysis_parent_sort": "document_nodes",
            "ix_document_sections_document_sort": "document_sections",
            "ix_tool_calls_agent_status": "tool_calls",
            "ix_tool_calls_claim_expires_at": "tool_calls",
            "ix_tool_calls_openai_call_id": "tool_calls",
            "ix_evidence_agent_path": "evidence",
            "ix_outbox_events_published_created_at": "outbox_events",
            "ix_snapshot_files_snapshot_parent": "snapshot_files",
            "ix_snapshot_files_snapshot_content_hash": "snapshot_files",
        }

        for index_name, table_name in required_indexes.items():
            with self.subTest(index=index_name):
                self.assertRegex(sql, rf"\bcreate\s+index\s+{index_name}\s+on\s+{table_name}\b")
        self.assertRegex(
            sql,
            r"create\s+index\s+ix_analyses_tenant_user_repository_url\s+on\s+analyses"
            r"\s+\(tenant_id,\s*created_by_user_id,\s*repository_url\s+text_pattern_ops\)",
        )
        self.assertIn("create extension if not exists pg_trgm", sql)
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_analysis_repositories_scope_url\s+on\s+analysis_repositories"
            r"\s+\(tenant_id,\s*created_by_user_id,\s*repository_url_hash\)",
        )
        self.assertRegex(
            sql,
            r"create\s+index\s+ix_analysis_repositories_label_trgm\s+on\s+analysis_repositories"
            r"\s+using\s+gin\s+\(repository_label\s+gin_trgm_ops\)",
        )
        self.assertRegex(
            sql,
            r"create\s+index\s+ix_analysis_repositories_text_trgm\s+on\s+analysis_repositories"
            r"\s+using\s+gin\s+\(search_text\s+gin_trgm_ops\)",
        )


def _migration_sql() -> str:
    return _normalize_sql(MIGRATION_PATH.read_text(encoding="utf-8"))


def _create_table_body(sql: str, table_name: str) -> str:
    match = re.search(rf"\bcreate\s+table\s+{table_name}\s+\((.*?)\);", sql, re.DOTALL)
    if match is None:
        raise AssertionError(f"CREATE TABLE statement not found for {table_name}")
    return match.group(1)


def _create_table_position(sql: str, table_name: str) -> int:
    match = re.search(rf"\bcreate\s+table\s+{table_name}\b", sql)
    if match is None:
        raise AssertionError(f"CREATE TABLE statement not found for {table_name}")
    return match.start()


def _normalize_sql(sql: str) -> str:
    sql = sql.lower()
    sql = re.sub(r"--.*", "", sql)
    return re.sub(r"\s+", " ", sql)


if __name__ == "__main__":
    unittest.main()
