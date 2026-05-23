from __future__ import annotations

from pathlib import Path
import re
import unittest

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
        self.assertRegex(_create_table_body(sql, "event_processing_claims"), r"\bclaim_expires_at\s+timestamptz\s+not\s+null\b")
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
        self.assertRegex(
            sql,
            r"create\s+unique\s+index\s+uq_snapshots_repo_commit_policy\s+on\s+snapshots"
            r"\s+\(repository_url_hash,\s*resolved_commit_sha,\s*snapshot_policy_hash\)",
        )

    def test_migration_defines_query_path_indexes(self) -> None:
        sql = _migration_sql()
        required_indexes = {
            "ix_analyses_tenant_created_at": "analyses",
            "ix_analyses_status_updated_at": "analyses",
            "ix_agent_sessions_analysis_id": "agent_sessions",
            "ix_agent_turns_agent_turn_index": "agent_turns",
            "ix_agent_stream_events_agent_seq": "agent_stream_events",
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


def _migration_sql() -> str:
    return _normalize_sql(MIGRATION_PATH.read_text(encoding="utf-8"))


def _create_table_body(sql: str, table_name: str) -> str:
    match = re.search(rf"\bcreate\s+table\s+{table_name}\s+\((.*?)\);", sql, re.DOTALL)
    if match is None:
        raise AssertionError(f"CREATE TABLE statement not found for {table_name}")
    return match.group(1)


def _normalize_sql(sql: str) -> str:
    sql = sql.lower()
    sql = re.sub(r"--.*", "", sql)
    return re.sub(r"\s+", " ", sql)


if __name__ == "__main__":
    unittest.main()
