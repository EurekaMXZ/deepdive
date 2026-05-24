from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.config import app_config_from_json, load_app_config_from_env, load_dotenv_if_exists


class EnvConfigTest(unittest.TestCase):
    def test_load_dotenv_writes_missing_environment_variables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "# local backend configuration",
                        "DATABASE_URL=postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                        "KAFKA_BOOTSTRAP_SERVERS='localhost:9092'",
                        'MINIO_BUCKET="deepdive-objects-custom"',
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(env_file)}, clear=True):
                loaded = load_dotenv_if_exists()

                self.assertTrue(loaded)
                self.assertEqual(
                    os.environ["DATABASE_URL"],
                    "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                )
                self.assertEqual(os.environ["KAFKA_BOOTSTRAP_SERVERS"], "localhost:9092")
                self.assertEqual(os.environ["MINIO_BUCKET"], "deepdive-objects-custom")

    def test_load_dotenv_does_not_override_existing_environment_variables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("DATABASE_URL=from-env-file\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "DEEPDIVE_ENV_FILE": str(env_file),
                    "DATABASE_URL": "from-real-environment",
                },
                clear=True,
            ):
                loaded = load_dotenv_if_exists()

                self.assertTrue(loaded)
                self.assertEqual(os.environ["DATABASE_URL"], "from-real-environment")

    def test_load_dotenv_returns_false_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_file = Path(tmpdir) / "missing.env"

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(missing_file)}, clear=True):
                self.assertFalse(load_dotenv_if_exists())

    def test_load_app_config_from_env_uses_backend_openai_settings(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPDIVE_ENV_FILE": str(Path(tempfile.gettempdir()) / "deepdive-missing.env"),
                "OPENAI_MODEL": "local-model",
                "OPENAI_REASONING_EFFORT": "low",
                "OPENAI_REASONING_SUMMARY": "detailed",
                "OPENAI_SERVICE_TIER": "default",
                "OPENAI_PARALLEL_TOOL_CALLS": "true",
                "OPENAI_USE_PREVIOUS_RESPONSE_ID": "true",
                "API_SHOW_MODEL_REASONING_SUMMARY": "false",
            },
            clear=True,
        ):
            config = load_app_config_from_env()

        self.assertEqual(config.openai.model, "local-model")
        self.assertEqual(config.openai.reasoning_effort, "low")
        self.assertEqual(config.openai.reasoning_summary, "detailed")
        self.assertEqual(config.openai.service_tier, "default")
        self.assertFalse(config.openai.parallel_tool_calls)
        self.assertTrue(config.openai.use_previous_response_id)
        self.assertFalse(config.openai.show_reasoning_summary)

    def test_load_app_config_from_env_uses_full_backend_settings_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "OPENAI_MODEL=dotenv-model",
                        "OPENAI_REASONING_EFFORT=high",
                        "OPENAI_REASONING_SUMMARY=concise",
                        "OPENAI_SERVICE_TIER=default",
                        "OPENAI_PARALLEL_TOOL_CALLS=true",
                        "OPENAI_USE_PREVIOUS_RESPONSE_ID=true",
                        "API_SHOW_MODEL_REASONING_SUMMARY=false",
                        "PROMPT_SYSTEM_INSTRUCTION_FILE=prompts/custom-system.md",
                        "PROMPT_DEVELOPER_INSTRUCTION_FILE=prompts/custom-developer.md",
                        "PROMPT_COMPACTION_INSTRUCTION_FILE=prompts/custom-compact.md",
                        "ANALYSIS_DEFAULT_PROFILE=security_review",
                        "ANALYSIS_GOAL_FILE=profiles/security_review.md",
                        "ANALYSIS_MAX_TURNS=12",
                        "ANALYSIS_MAX_TOOL_CALLS=34",
                        "ANALYSIS_AUTO_COMPACT_THRESHOLD_TOKENS=5678",
                        "TOOLS_ENABLED=list_files,read_file",
                        "TOOL_READ_FILE_DEFAULT_LINES=20",
                        "TOOL_READ_FILE_MAX_LINES=40",
                        "TOOL_READ_FILE_MAX_BYTES=8192",
                        "TOOL_SEARCH_TEXT_MAX_RESULTS=25",
                        "TOOL_SEARCH_TEXT_TIMEOUT_SECONDS=6",
                        "TOOL_SEARCH_TEXT_MAX_OUTPUT_BYTES=32768",
                        "SNAPSHOT_MAX_FILE_BYTES=2048",
                        "SNAPSHOT_MAX_GIT_BUNDLE_BYTES=4096",
                        "SNAPSHOT_LFS_POLICY=metadata_only",
                        "SNAPSHOT_SUBMODULE_POLICY=skip",
                        "SNAPSHOT_BINARY_POLICY=skip",
                        "CACHE_ROOT_DIR=D:/cache/deepdive",
                        "CACHE_MAX_WORKER_CACHE_BYTES=123456",
                        "CACHE_MAX_PREFIX_BYTES=654321",
                        "CACHE_TTL_DAYS=3",
                        "CACHE_MIN_FREE_DISK_PERCENT=22",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(env_file)}, clear=True):
                config = load_app_config_from_env()

        self.assertEqual(config.openai.model, "dotenv-model")
        self.assertEqual(config.openai.reasoning_effort, "high")
        self.assertEqual(config.openai.reasoning_summary, "concise")
        self.assertEqual(config.openai.service_tier, "default")
        self.assertFalse(config.openai.parallel_tool_calls)
        self.assertTrue(config.openai.use_previous_response_id)
        self.assertFalse(config.openai.show_reasoning_summary)

        self.assertEqual(config.prompt.system_instruction_file, "prompts/custom-system.md")
        self.assertEqual(config.prompt.developer_instruction_file, "prompts/custom-developer.md")
        self.assertEqual(config.prompt.compaction_instruction_file, "prompts/custom-compact.md")

        self.assertEqual(config.analysis.default_profile, "security_review")
        profile = config.analysis.profiles["security_review"]
        self.assertEqual(profile.goal_file, "profiles/security_review.md")
        self.assertEqual(profile.max_turns, 12)
        self.assertEqual(profile.max_tool_calls, 34)
        self.assertEqual(profile.auto_compact_threshold_tokens, 5678)

        self.assertEqual(config.tools.enabled, ("list_files", "read_file"))
        self.assertEqual(config.tools.read_file.default_lines, 20)
        self.assertEqual(config.tools.read_file.max_lines, 40)
        self.assertEqual(config.tools.read_file.max_bytes, 8192)
        self.assertEqual(config.tools.search_text.max_results, 25)
        self.assertEqual(config.tools.search_text.timeout_seconds, 6)
        self.assertEqual(config.tools.search_text.max_output_bytes, 32768)

        self.assertEqual(config.snapshot.max_file_bytes, 2048)
        self.assertEqual(config.snapshot.max_git_bundle_bytes, 4096)
        self.assertEqual(config.snapshot.lfs_policy, "metadata_only")
        self.assertEqual(config.snapshot.submodule_policy, "skip")
        self.assertEqual(config.snapshot.binary_policy, "skip")

        self.assertEqual(config.cache.root_dir, "D:/cache/deepdive")
        self.assertEqual(config.cache.max_worker_cache_bytes, 123456)
        self.assertEqual(config.cache.max_prefix_bytes, 654321)
        self.assertEqual(config.cache.ttl_days, 3)
        self.assertEqual(config.cache.min_free_disk_percent, 22)

    def test_load_app_config_from_env_reads_profile_goal_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "profiles").mkdir()
            (root / "profiles" / "security_review.md").write_text("检查安全边界。", encoding="utf-8")
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "ANALYSIS_DEFAULT_PROFILE=security_review",
                        "ANALYSIS_GOAL_FILE=profiles/security_review.md",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(env_file)}, clear=True), patch("os.getcwd", return_value=str(root)):
                config = load_app_config_from_env()

        self.assertEqual(config.analysis.profiles["security_review"].goal, "检查安全边界。")

    def test_app_config_from_json_restores_reasoning_summary_settings(self) -> None:
        config = app_config_from_json(
            {
                "openai": {
                    "model": "snapshot-model",
                    "reasoning_effort": "low",
                    "reasoning_summary": "detailed",
                    "service_tier": "priority",
                    "parallel_tool_calls": False,
                    "use_previous_response_id": True,
                    "show_reasoning_summary": False,
                }
            }
        )

        self.assertEqual(config.openai.reasoning_summary, "detailed")
        self.assertFalse(config.openai.show_reasoning_summary)

    def test_web_search_config_loads_without_serializing_tavily_api_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPDIVE_ENV_FILE": str(Path(tempfile.gettempdir()) / "deepdive-missing.env"),
                "TOOLS_ENABLED": "web_search,document_create,document_get,document_update,document_delete,document_finalize",
                "TOOL_WEB_SEARCH_MAX_RESULTS": "8",
                "TOOL_WEB_SEARCH_TIMEOUT_SECONDS": "12",
                "TOOL_WEB_SEARCH_MAX_QUERY_CHARS": "400",
                "OPENAI_WEB_SEARCH_ENABLED": "true",
                "OPENAI_WEB_SEARCH_CONTEXT_SIZE": "high",
                "OPENAI_WEB_SEARCH_EXTERNAL_WEB_ACCESS": "false",
                "OPENAI_WEB_SEARCH_INCLUDE_SOURCES": "true",
                "OPENAI_WEB_SEARCH_ALLOWED_DOMAINS": "example.com,docs.example.com",
                "OPENAI_WEB_SEARCH_RETURN_TOKEN_BUDGET": "default",
                "TAVILY_API_KEY": "tvly-test-secret",
            },
            clear=True,
        ):
            config = load_app_config_from_env()

        self.assertEqual(config.tools.enabled, ("web_search", "document_create", "document_get", "document_update", "document_delete", "document_finalize"))
        self.assertEqual(config.tools.web_search.max_results, 8)
        self.assertEqual(config.tools.web_search.timeout_seconds, 12)
        self.assertEqual(config.tools.web_search.max_query_chars, 400)
        self.assertTrue(config.tools.openai_web_search.enabled)
        self.assertEqual(config.tools.openai_web_search.search_context_size, "high")
        self.assertFalse(config.tools.openai_web_search.external_web_access)
        self.assertTrue(config.tools.openai_web_search.include_sources)
        self.assertEqual(config.tools.openai_web_search.allowed_domains, ("example.com", "docs.example.com"))
        self.assertEqual(config.tools.openai_web_search.blocked_domains, ())
        self.assertEqual(config.tools.openai_web_search.return_token_budget, "default")
        self.assertNotIn("tvly-test-secret", str(config.to_json_dict()))

    def test_app_config_from_json_restores_new_tool_configs(self) -> None:
        config = app_config_from_json(
            {
                "tools": {
                    "enabled": ["web_search", "document_create"],
                    "web_search": {
                        "max_results": 6,
                        "timeout_seconds": 9,
                        "max_query_chars": 350,
                    },
                    "openai_web_search": {
                        "enabled": True,
                        "search_context_size": "low",
                        "external_web_access": False,
                        "include_sources": True,
                        "allowed_domains": ["example.com"],
                        "return_token_budget": "unlimited",
                    },
                }
            }
        )

        self.assertEqual(config.tools.enabled, ("web_search", "document_create"))
        self.assertEqual(config.tools.web_search.max_results, 6)
        self.assertEqual(config.tools.web_search.timeout_seconds, 9)
        self.assertEqual(config.tools.web_search.max_query_chars, 350)
        self.assertTrue(config.tools.openai_web_search.enabled)
        self.assertEqual(config.tools.openai_web_search.search_context_size, "low")
        self.assertFalse(config.tools.openai_web_search.external_web_access)
        self.assertTrue(config.tools.openai_web_search.include_sources)
        self.assertEqual(config.tools.openai_web_search.allowed_domains, ("example.com",))
        self.assertEqual(config.tools.openai_web_search.blocked_domains, ())
        self.assertEqual(config.tools.openai_web_search.return_token_budget, "unlimited")

    def test_openai_web_search_config_rejects_api_incompatible_values_from_env(self) -> None:
        invalid_envs = [
            {"OPENAI_WEB_SEARCH_CONTEXT_SIZE": "giant"},
            {"OPENAI_WEB_SEARCH_RETURN_TOKEN_BUDGET": "42"},
            {"OPENAI_WEB_SEARCH_ALLOWED_DOMAINS": "https://example.com"},
            {"OPENAI_WEB_SEARCH_ALLOWED_DOMAINS": ",".join(f"example{i}.com" for i in range(101))},
            {"OPENAI_WEB_SEARCH_ALLOWED_DOMAINS": "example.com", "OPENAI_WEB_SEARCH_BLOCKED_DOMAINS": "blocked.example"},
        ]

        for env in invalid_envs:
            with self.subTest(env=env):
                values = {
                    "DEEPDIVE_ENV_FILE": str(Path(tempfile.gettempdir()) / "deepdive-missing.env"),
                    "OPENAI_WEB_SEARCH_ENABLED": "true",
                    **env,
                }
                with patch.dict(os.environ, values, clear=True):
                    with self.assertRaises(ValueError):
                        load_app_config_from_env()

    def test_openai_web_search_config_rejects_api_incompatible_values_from_json(self) -> None:
        invalid_sections = [
            {"enabled": True, "search_context_size": "giant"},
            {"enabled": True, "return_token_budget": "42"},
            {"enabled": True, "blocked_domains": ["http://blocked.example"]},
            {"enabled": True, "allowed_domains": [f"example{i}.com" for i in range(101)]},
            {"enabled": True, "allowed_domains": ["example.com"], "blocked_domains": ["blocked.example"]},
        ]

        for section in invalid_sections:
            with self.subTest(section=section):
                with self.assertRaises(ValueError):
                    app_config_from_json({"tools": {"openai_web_search": section}})

    def test_web_search_config_rejects_invalid_limits_from_env_and_json(self) -> None:
        invalid_envs = [
            {"TOOL_WEB_SEARCH_MAX_RESULTS": "0"},
            {"TOOL_WEB_SEARCH_MAX_RESULTS": "11"},
            {"TOOL_WEB_SEARCH_TIMEOUT_SECONDS": "0"},
            {"TOOL_WEB_SEARCH_MAX_QUERY_CHARS": "0"},
        ]

        for env in invalid_envs:
            with self.subTest(env=env):
                values = {
                    "DEEPDIVE_ENV_FILE": str(Path(tempfile.gettempdir()) / "deepdive-missing.env"),
                    **env,
                }
                with patch.dict(os.environ, values, clear=True):
                    with self.assertRaises(ValueError):
                        load_app_config_from_env()

        invalid_jsons = [
            {"max_results": 0},
            {"max_results": 11},
            {"timeout_seconds": 0},
            {"max_query_chars": 0},
        ]
        for section in invalid_jsons:
            with self.subTest(section=section):
                with self.assertRaises(ValueError):
                    app_config_from_json({"tools": {"web_search": section}})


if __name__ == "__main__":
    unittest.main()
