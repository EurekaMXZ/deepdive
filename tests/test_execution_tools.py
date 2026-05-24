from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from backend.cache import LocalSourceCache
from backend.config import (
    AppConfig,
    CacheConfig,
    ReadFileToolConfig,
    SearchTextToolConfig,
    ToolsConfig,
    WebSearchToolConfig,
)
from backend.events import EventEnvelope, EventType
from backend.execution import (
    DEFAULT_TOOL_POLICY_HASH,
    DEFAULT_TOOL_REGISTRY_VERSION,
    PermissionDecision,
    PermissionEngine,
    SnapshotToolRepository,
    SourceToolExecutor,
    ToolCapability,
    ToolExecutionContext,
    ToolRegistry,
)
from backend.execution.repository import PostgresToolCallRepository
from backend.ids import new_uuid7
from backend.storage import InMemoryObjectStorage
from backend.workers.execution import ExecutionCommandHandler


class SourceToolExecutorTest(unittest.IsolatedAsyncioTestCase):
    def test_registry_version_and_policy_hash_have_stable_audit_shapes(self) -> None:
        self.assertIsInstance(DEFAULT_TOOL_REGISTRY_VERSION, str)
        self.assertTrue(DEFAULT_TOOL_REGISTRY_VERSION)
        self.assertRegex(DEFAULT_TOOL_POLICY_HASH, r"^sha256:[0-9a-f]{64}$")

    def test_tool_registry_schema_exposes_filters_cursors_and_nullable_read_defaults(self) -> None:
        tools = {tool["name"]: tool["parameters"] for tool in ToolRegistry.default().response_tools()}

        self.assertIn("glob", tools["list_files"]["properties"])
        self.assertIn("cursor", tools["list_files"]["properties"])
        self.assertIn("glob", tools["search_file"]["properties"])
        self.assertIn("cursor", tools["search_file"]["properties"])
        self.assertIn("path_glob", tools["search_text"]["properties"])
        self.assertIn("cursor", tools["search_text"]["properties"])
        self.assertEqual(tools["read_file"]["properties"]["start_line"]["type"], ["integer", "null"])
        self.assertEqual(tools["read_file"]["properties"]["end_line"]["type"], ["integer", "null"])
        self.assertEqual(tools["read_file"]["properties"]["max_bytes"]["type"], ["integer", "null"])

    def test_tool_registry_schema_exposes_web_search_and_document_tools(self) -> None:
        registry = ToolRegistry.from_config(
            ToolsConfig(
                enabled=(
                    "web_search",
                    "document_create",
                    "document_get",
                    "document_update",
                    "document_delete",
                    "document_finalize",
                )
            )
        )
        tools = {tool["name"]: tool for tool in registry.response_tools()}

        self.assertEqual(
            set(tools),
            {
                "web_search",
                "document_create",
                "document_get",
                "document_update",
                "document_delete",
                "document_finalize",
            },
        )
        self.assertEqual(tools["web_search"]["parameters"]["properties"]["search_depth"]["enum"], ["basic", "advanced"])
        self.assertEqual(
            tools["web_search"]["parameters"]["properties"]["topic"]["enum"], ["general", "news", "finance"]
        )
        self.assertEqual(tools["web_search"]["parameters"]["properties"]["max_results"]["maximum"], 10)
        self.assertIn("expected_version", tools["document_update"]["parameters"]["required"])
        self.assertTrue(tools["document_create"]["description"].startswith("Create"))

    def test_tool_registry_rejects_unknown_enabled_tools(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown enabled tools: missing_tool"):
            ToolRegistry.from_config(ToolsConfig(enabled=("list_files", "missing_tool")))

    def test_tool_registry_definitions_include_policy_metadata(self) -> None:
        registry = ToolRegistry.from_config(
            ToolsConfig(enabled=("list_files", "web_search", "document_create", "document_get"))
        )
        definitions = {tool.name: tool for tool in registry.tools}

        self.assertEqual(definitions["list_files"].capability, ToolCapability.SOURCE_READ)
        self.assertTrue(definitions["list_files"].read_only)
        self.assertTrue(definitions["list_files"].idempotent)
        self.assertEqual(definitions["web_search"].capability, ToolCapability.EXTERNAL_NETWORK)
        self.assertTrue(definitions["web_search"].read_only)
        self.assertFalse(definitions["web_search"].idempotent)
        self.assertEqual(definitions["document_create"].capability, ToolCapability.ARTIFACT_WRITE)
        self.assertFalse(definitions["document_create"].read_only)
        self.assertFalse(definitions["document_create"].idempotent)
        self.assertTrue(definitions["document_create"].requires_analysis_id)
        self.assertEqual(definitions["document_get"].capability, ToolCapability.ARTIFACT_READ)
        self.assertTrue(definitions["document_get"].requires_analysis_id)

    def test_permission_result_includes_tool_policy_metadata(self) -> None:
        result = PermissionEngine().evaluate_result(
            tool_name="document_create",
            arguments={"title": "Draft", "kind": "markdown", "content": "# Draft"},
            tools_config=ToolsConfig(enabled=("document_create",)),
        )

        self.assertEqual(result.decision, PermissionDecision.ALLOW)
        self.assertEqual(result.capability, ToolCapability.ARTIFACT_WRITE)
        self.assertFalse(result.read_only)
        self.assertFalse(result.idempotent)
        self.assertTrue(result.requires_analysis_id)

    def test_source_tool_executor_registers_explicit_handlers_for_all_function_tools(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )
        registry = ToolRegistry.from_config(
            ToolsConfig(
                enabled=(
                    "list_files",
                    "search_file",
                    "search_text",
                    "read_file",
                    "web_search",
                    "document_create",
                    "document_get",
                    "document_update",
                    "document_delete",
                    "document_finalize",
                )
            )
        )

        self.assertEqual(set(executor.tool_handlers), {tool.name for tool in registry.tools})
        self.assertIs(executor.tool_handlers["document_create"], executor.tool_handlers["document_update"])
        self.assertIs(executor.tool_handlers["document_delete"], executor.tool_handlers["document_finalize"])

    async def test_web_search_returns_not_configured_without_api_key(self) -> None:
        with patch.dict(os.environ, {"TAVILY_API_KEY": ""}):
            executor = SourceToolExecutor(
                repository=FakeToolRepository(files=[]),
                storage=InMemoryObjectStorage(),
                cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
                permission_engine=PermissionEngine(),
            )

            result = await executor.execute(
                ToolExecutionContext(
                    tool_call_id=new_uuid7(), analysis_id=new_uuid7(), agent_id=new_uuid7(), snapshot_id=new_uuid7()
                ),
                "web_search",
                {"query": "deepdive", "max_results": 3},
                config=AppConfig(tools=ToolsConfig(enabled=("web_search",))),
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "WEB_SEARCH_NOT_CONFIGURED")

    async def test_web_search_rejects_unsafe_domains(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
            tavily_api_key="tvly-test-key",
        )

        for domain in ["localhost", "127.0.0.1", "http://example.com"]:
            with self.subTest(domain=domain):
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(), analysis_id=new_uuid7(), agent_id=new_uuid7(), snapshot_id=new_uuid7()
                    ),
                    "web_search",
                    {"query": "deepdive", "include_domains": [domain]},
                    config=AppConfig(tools=ToolsConfig(enabled=("web_search",))),
                )

                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")

    async def test_web_search_rejects_invalid_time_range_before_calling_tavily(self) -> None:
        client = FakeTavilyClient({"results": []})
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
            tavily_api_key="tvly-test-key",
            tavily_client=client,
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(), analysis_id=new_uuid7(), agent_id=new_uuid7(), snapshot_id=new_uuid7()
            ),
            "web_search",
            {"query": "deepdive", "time_range": "decade"},
            config=AppConfig(tools=ToolsConfig(enabled=("web_search",))),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")
        self.assertEqual(client.requests, [])

    async def test_web_search_enforces_configured_max_results(self) -> None:
        client = FakeTavilyClient({"results": []})
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
            web_search_config=WebSearchToolConfig(max_results=3),
            tavily_api_key="tvly-test-key",
            tavily_client=client,
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(), analysis_id=new_uuid7(), agent_id=new_uuid7(), snapshot_id=new_uuid7()
            ),
            "web_search",
            {"query": "deepdive", "max_results": 10},
            config=AppConfig(tools=ToolsConfig(enabled=("web_search",), web_search=WebSearchToolConfig(max_results=3))),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(client.requests[0]["max_results"], 3)

    async def test_web_search_uses_config_snapshot_not_executor_startup_config(self) -> None:
        client = FakeTavilyClient({"results": []})
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
            web_search_config=WebSearchToolConfig(max_results=10),
            tavily_api_key="tvly-test-key",
            tavily_client=client,
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(), analysis_id=new_uuid7(), agent_id=new_uuid7(), snapshot_id=new_uuid7()
            ),
            "web_search",
            {"query": "deepdive", "max_results": 10},
            config=AppConfig(tools=ToolsConfig(enabled=("web_search",), web_search=WebSearchToolConfig(max_results=3))),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(client.requests[0]["max_results"], 3)

    async def test_web_search_rejects_invalid_dates_and_domain_overflow_before_calling_tavily(self) -> None:
        client = FakeTavilyClient({"results": []})
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
            tavily_api_key="tvly-test-key",
            tavily_client=client,
        )

        cases = [
            {"query": "deepdive", "start_date": "2026/05/01"},
            {"query": "deepdive", "start_date": "2026-05-02", "end_date": "2026-05-01"},
            {"query": "deepdive", "include_domains": [f"example{i}.com" for i in range(21)]},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(), analysis_id=new_uuid7(), agent_id=new_uuid7(), snapshot_id=new_uuid7()
                    ),
                    "web_search",
                    arguments,
                    config=AppConfig(tools=ToolsConfig(enabled=("web_search",))),
                )

                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")
        self.assertEqual(client.requests, [])

    async def test_web_search_success_normalizes_results_and_writes_result_ref(self) -> None:
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        storage = InMemoryObjectStorage()
        client = FakeTavilyClient(
            {
                "results": [
                    {
                        "title": "DeepDive",
                        "url": "https://example.com/deepdive",
                        "content": "A repository analysis system.",
                        "score": 0.91,
                        "published_date": "2026-05-01",
                        "domain": "example.com",
                        "raw_content": "raw content must not be returned by default",
                    }
                ],
                "query": "deepdive",
                "response_time": 1.2,
            }
        )
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=storage,
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
            tavily_api_key="tvly-test-key",
            tavily_client=client,
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=tool_call_id, analysis_id=new_uuid7(), agent_id=new_uuid7(), snapshot_id=snapshot_id
            ),
            "web_search",
            {
                "query": "deepdive",
                "search_depth": "advanced",
                "max_results": 20,
                "topic": "general",
                "include_domains": ["example.com"],
            },
            config=AppConfig(tools=ToolsConfig(enabled=("web_search",))),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool_name"], "web_search")
        self.assertEqual(
            result["scope"],
            {"type": "external_web", "snapshot_id": str(snapshot_id), "provider": "tavily"},
        )
        self.assertEqual(result["result_ref"], f"tool-results/{tool_call_id}.json")
        self.assertIn(result["result_ref"], storage.objects)
        self.assertEqual(client.requests[0]["max_results"], 10)
        self.assertFalse(client.requests[0]["include_raw_content"])
        self.assertFalse(client.requests[0]["include_answer"])
        self.assertFalse(client.requests[0]["include_images"])
        self.assertEqual(
            result["result"]["results"],
            [
                {
                    "title": "DeepDive",
                    "url": "https://example.com/deepdive",
                    "content": "A repository analysis system.",
                    "score": 0.91,
                    "published_date": "2026-05-01",
                    "domain": "example.com",
                }
            ],
        )
        stored_payload = storage.objects[result["result_ref"]].decode("utf-8")
        self.assertNotIn("tvly-test-key", stored_payload)
        self.assertNotIn("raw_content", stored_payload)

    async def test_read_file_returns_bounded_line_range_and_evidence(self) -> None:
        snapshot_id = new_uuid7()
        agent_id = new_uuid7()
        tool_call_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/a.py", b"one\ntwo\nthree\nfour\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                {
                    "path": "pkg/a.py",
                    "parent_path": "pkg",
                    "name": "a.py",
                    "entry_kind": "file",
                    "content_key": "blob/a.py",
                    "content_hash": "sha256:abc",
                    "size_bytes": 19,
                    "line_count": 4,
                    "is_binary": False,
                    "is_large": False,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=LocalSourceCache(root_dir=Path(tmpdir)),
                permission_engine=PermissionEngine(),
                read_config=ReadFileToolConfig(default_lines=2, max_lines=3, max_bytes=100),
            )

            result = await executor.execute(
                ToolExecutionContext(
                    tool_call_id=tool_call_id,
                    agent_id=agent_id,
                    snapshot_id=snapshot_id,
                ),
                "read_file",
                {"path": "pkg/a.py", "start_line": 2, "end_line": 4},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["path"], "pkg/a.py")
        self.assertEqual(result["result"]["start_line"], 2)
        self.assertEqual(result["result"]["end_line"], 4)
        self.assertEqual(result["result"]["content"], "two\nthree\nfour\n")
        self.assertFalse(result["truncated"])
        self.assertEqual(len(repository.evidence), 1)
        self.assertEqual(repository.evidence[0]["path"], "pkg/a.py")

    async def test_read_file_stores_evidence_snippet_as_object_ref(self) -> None:
        snapshot_id = new_uuid7()
        agent_id = new_uuid7()
        tool_call_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/a.py", b"one\ntwo\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "pkg/a.py",
                    "pkg",
                    "a.py",
                    "file",
                    content_key="blob/a.py",
                    content_hash="sha256:abc",
                    line_count=2,
                    size_bytes=8,
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=LocalSourceCache(root_dir=Path(tmpdir)),
                permission_engine=PermissionEngine(),
            )

            result = await executor.execute(
                ToolExecutionContext(
                    tool_call_id=tool_call_id,
                    agent_id=agent_id,
                    snapshot_id=snapshot_id,
                ),
                "read_file",
                {"path": "pkg/a.py", "start_line": 1, "end_line": 1},
            )

        self.assertTrue(result["ok"])
        self.assertTrue(repository.evidence[0]["snippet_ref"].startswith("evidence/"))
        self.assertEqual(storage.objects[repository.evidence[0]["snippet_ref"]], b"one\n")
        self.assertEqual(result["result_ref"], f"tool-results/{tool_call_id}.json")
        self.assertIn(result["result_ref"], storage.objects)

    async def test_read_file_denies_path_traversal(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "read_file",
            {"path": "../secret.txt"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UNSAFE_PATH")

    async def test_read_file_denies_windows_drive_path(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "read_file",
            {"path": "C:/Windows/win.ini"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UNSAFE_PATH")

    async def test_read_file_denies_secret_paths(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "read_file",
            {"path": ".env"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SECRET_PATH_DENIED")

    async def test_read_file_denies_high_confidence_secret_paths(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        for path in [
            ".git-credentials",
            ".docker/config.json",
            "credentials.json",
            "service-account.json",
            "private.pem",
            "secrets.yaml",
        ]:
            with self.subTest(path=path):
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(),
                        agent_id=new_uuid7(),
                        snapshot_id=new_uuid7(),
                    ),
                    "read_file",
                    {"path": path},
                )

                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "SECRET_PATH_DENIED")

    async def test_search_file_denies_secret_glob(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "search_file",
            {"query": "env", "glob": "**/.env", "max_results": 5},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SECRET_PATH_DENIED")

    async def test_search_file_denies_high_confidence_secret_glob(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "search_file",
            {"query": "credentials", "glob": "**/*credentials*.json", "max_results": 5},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SECRET_PATH_DENIED")

    async def test_read_file_rejects_end_line_before_start_line(self) -> None:
        storage = CountingStorage()
        storage.put_bytes("blob/a.py", b"one\ntwo\n", content_type="text/plain")
        executor = SourceToolExecutor(
            repository=FakeToolRepository(
                files=[
                    _file(
                        "pkg/a.py",
                        "pkg",
                        "a.py",
                        "file",
                        content_key="blob/a.py",
                        content_hash="sha256:abc",
                        line_count=2,
                        size_bytes=8,
                    )
                ]
            ),
            storage=storage,
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "read_file",
            {"path": "pkg/a.py", "start_line": 2, "end_line": 1},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")

    async def test_read_file_rejects_negative_max_bytes(self) -> None:
        storage = CountingStorage()
        storage.put_bytes("blob/a.py", b"one very long line\n", content_type="text/plain")
        executor = SourceToolExecutor(
            repository=FakeToolRepository(
                files=[
                    _file(
                        "pkg/a.py",
                        "pkg",
                        "a.py",
                        "file",
                        content_key="blob/a.py",
                        content_hash="sha256:abc",
                        line_count=1,
                        size_bytes=19,
                    )
                ]
            ),
            storage=storage,
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "read_file",
            {"path": "pkg/a.py", "start_line": 1, "end_line": 1, "max_bytes": -1},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")

    async def test_cache_rejects_colon_paths_even_from_snapshot_metadata(self) -> None:
        cache = LocalSourceCache(root_dir=Path(tempfile.mkdtemp()))

        with self.assertRaisesRegex(ValueError, "unsafe"):
            cache.file_path(new_uuid7(), "C:/Windows/win.ini")

    async def test_list_files_and_search_file_use_snapshot_metadata(self) -> None:
        snapshot_id = new_uuid7()
        repository = FakeToolRepository(
            files=[
                _file("backend", None, "backend", "directory"),
                _file("backend/api/app.py", "backend/api", "app.py", "file"),
                _file("backend/workers/outbox.py", "backend/workers", "outbox.py", "file"),
            ]
        )
        executor = SourceToolExecutor(
            repository=repository,
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )
        context = ToolExecutionContext(
            tool_call_id=new_uuid7(),
            agent_id=new_uuid7(),
            snapshot_id=snapshot_id,
        )

        listed = await executor.execute(context, "list_files", {"path": "backend", "recursive": True})
        searched = await executor.execute(context, "search_file", {"query": "app", "max_results": 10})

        self.assertTrue(listed["ok"])
        self.assertEqual(
            [item["path"] for item in listed["result"]["items"]], ["backend/api/app.py", "backend/workers/outbox.py"]
        )
        self.assertTrue(searched["ok"])
        self.assertEqual([item["path"] for item in searched["result"]["items"]], ["backend/api/app.py"])

    async def test_list_files_and_search_file_hide_secret_metadata(self) -> None:
        snapshot_id = new_uuid7()
        repository = FakeToolRepository(
            files=[
                _file(".env", None, ".env", "file"),
                _file(".git/config", ".git", "config", "file"),
                _file("credentials.json", None, "credentials.json", "file"),
                _file("src/app.py", "src", "app.py", "file"),
            ]
        )
        executor = SourceToolExecutor(
            repository=repository,
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )
        context = ToolExecutionContext(
            tool_call_id=new_uuid7(),
            agent_id=new_uuid7(),
            snapshot_id=snapshot_id,
        )

        listed = await executor.execute(context, "list_files", {"path": "", "recursive": True, "max_results": 10})
        env_search = await executor.execute(context, "search_file", {"query": "env", "max_results": 10})
        credentials_search = await executor.execute(context, "search_file", {"query": "credentials", "max_results": 10})

        self.assertTrue(listed["ok"])
        self.assertEqual([item["path"] for item in listed["result"]["items"]], ["src/app.py"])
        self.assertTrue(env_search["ok"])
        self.assertEqual(env_search["result"]["items"], [])
        self.assertTrue(credentials_search["ok"])
        self.assertEqual(credentials_search["result"]["items"], [])

    async def test_list_files_supports_glob_cursor_and_next_cursor(self) -> None:
        snapshot_id = new_uuid7()
        repository = FakeToolRepository(
            files=[
                _file("backend/api/app.py", "backend/api", "app.py", "file"),
                _file("backend/api/routes.py", "backend/api", "routes.py", "file"),
                _file("backend/api/schema.json", "backend/api", "schema.json", "file"),
            ]
        )
        executor = SourceToolExecutor(
            repository=repository,
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        listed = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=snapshot_id,
            ),
            "list_files",
            {"path": "backend/api", "recursive": True, "glob": "**/*.py", "max_results": 1, "cursor": "1"},
        )

        self.assertTrue(listed["ok"])
        self.assertEqual([item["path"] for item in listed["result"]["items"]], ["backend/api/routes.py"])
        self.assertIsNone(listed["next_cursor"])
        self.assertEqual(repository.list_file_calls[-1]["glob"], "**/*.py")
        self.assertEqual(repository.list_file_calls[-1]["cursor"], "1")

    async def test_search_file_supports_glob_cursor_and_next_cursor(self) -> None:
        snapshot_id = new_uuid7()
        repository = FakeToolRepository(
            files=[
                _file("backend/api/app.py", "backend/api", "app.py", "file"),
                _file("backend/api/routes.py", "backend/api", "routes.py", "file"),
                _file("backend/api/schema.json", "backend/api", "schema.json", "file"),
            ]
        )
        executor = SourceToolExecutor(
            repository=repository,
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        searched = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=snapshot_id,
            ),
            "search_file",
            {"query": "backend/api", "glob": "**/*.py", "max_results": 1, "cursor": "1"},
        )

        self.assertTrue(searched["ok"])
        self.assertEqual([item["path"] for item in searched["result"]["items"]], ["backend/api/routes.py"])
        self.assertIsNone(searched["next_cursor"])
        self.assertEqual(repository.search_file_calls[-1]["glob"], "**/*.py")
        self.assertEqual(repository.search_file_calls[-1]["cursor"], "1")

    async def test_list_files_treats_empty_path_as_repository_root(self) -> None:
        snapshot_id = new_uuid7()
        repository = FakeToolRepository(
            files=[
                _file("backend", None, "backend", "directory"),
                _file("README.md", None, "README.md", "file"),
                _file("backend/api/app.py", "backend/api", "app.py", "file"),
            ]
        )
        executor = SourceToolExecutor(
            repository=repository,
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        listed = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=snapshot_id,
            ),
            "list_files",
            {"path": "", "recursive": False, "max_results": 10},
        )

        self.assertTrue(listed["ok"])
        self.assertEqual([item["path"] for item in listed["result"]["items"]], ["backend", "README.md"])

    async def test_search_text_uses_prefix_cache_and_ripgrep_json(self) -> None:
        snapshot_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/app.py", b"from fastapi import FastAPI\napp = FastAPI()\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/api/app.py",
                    "backend/api",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:app",
                    line_count=2,
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=LocalSourceCache(root_dir=Path(tmpdir)),
                permission_engine=PermissionEngine(),
                search_config=SearchTextToolConfig(max_results=10, timeout_seconds=5, max_output_bytes=65536),
            )
            result = await executor.execute(
                ToolExecutionContext(
                    tool_call_id=new_uuid7(),
                    agent_id=new_uuid7(),
                    snapshot_id=snapshot_id,
                ),
                "search_text",
                {"query": "from fastapi", "path_prefix": "backend/", "max_results": 5},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["matches"][0]["path"], "backend/api/app.py")
        self.assertEqual(result["result"]["matches"][0]["line_number"], 1)
        self.assertEqual(len(repository.evidence), 1)

    async def test_search_text_rejects_empty_query(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "search_text",
            {"query": "  ", "path_prefix": "", "max_results": 5},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")

    async def test_search_text_uses_streaming_ripgrep_budget(self) -> None:
        snapshot_id = new_uuid7()
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/app.py",
                    "backend",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:d29210777777dac0b3d12f6a656a073c9ba717cf6932dbc01b0cc6dc1e7779b8",
                    line_count=1,
                    size_bytes=7,
                )
            ]
        )
        storage = InMemoryObjectStorage()
        storage.put_bytes("blob/app.py", b"needle\n", content_type="text/plain")

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LocalSourceCache(root_dir=Path(tmpdir))
            match_path = cache.file_path(snapshot_id, "backend/app.py")
            output = (
                json.dumps(
                    {
                        "type": "match",
                        "data": {
                            "path": {"text": str(match_path)},
                            "line_number": 1,
                            "lines": {"text": "needle\n"},
                        },
                    }
                )
                + "\n"
            )
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=cache,
                permission_engine=PermissionEngine(),
                search_config=SearchTextToolConfig(max_results=10, timeout_seconds=5, max_output_bytes=len(output) - 2),
            )

            with patch(
                "backend.execution._run_ripgrep_json", return_value=(output[: len(output) - 2], True, 0, "")
            ) as run_mock:
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(),
                        agent_id=new_uuid7(),
                        snapshot_id=snapshot_id,
                    ),
                    "search_text",
                    {"query": "needle", "path_prefix": "backend/", "max_results": 5},
                )

        self.assertTrue(result["ok"])
        self.assertTrue(result["truncated"])
        self.assertEqual(run_mock.call_args.kwargs["max_output_bytes"], len(output) - 2)

    async def test_search_text_invokes_ripgrep_with_explicit_pattern_and_path_separator(self) -> None:
        snapshot_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/app.py", b"needle\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/api/app.py",
                    "backend/api",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:d29210777777dac0b3d12f6a656a073c9ba717cf6932dbc01b0cc6dc1e7779b8",
                    line_count=1,
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=LocalSourceCache(root_dir=Path(tmpdir)),
                permission_engine=PermissionEngine(),
            )
            with patch("backend.execution._run_ripgrep_json") as run_mock:
                run_mock.return_value = ("", False, 1, "")

                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(),
                        agent_id=new_uuid7(),
                        snapshot_id=snapshot_id,
                    ),
                    "search_text",
                    {"query": "-n", "path_prefix": "backend/", "max_results": 5},
                )

        self.assertTrue(result["ok"])
        argv = run_mock.call_args.args[0]
        self.assertIn("-e", argv)
        self.assertEqual(argv[argv.index("-e") + 1], "-n")
        self.assertIn("--hidden", argv)
        self.assertIn("--no-ignore", argv)
        self.assertIn("--no-ignore-global", argv)
        self.assertIn("--", argv)
        self.assertGreater(argv.index("--"), argv.index("-e"))

    async def test_search_text_denies_secret_path_glob(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        result = await executor.execute(
            ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
            ),
            "search_text",
            {"query": "token", "path_prefix": "", "path_glob": "**/.env", "max_results": 5},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SECRET_PATH_DENIED")

    async def test_search_text_denies_high_confidence_secret_path_glob(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        for path_glob in ["**/*.pem", "**/*.key", "**/service-account*.json", "**/secrets.yaml"]:
            with self.subTest(path_glob=path_glob):
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(),
                        agent_id=new_uuid7(),
                        snapshot_id=new_uuid7(),
                    ),
                    "search_text",
                    {"query": "token", "path_prefix": "", "path_glob": path_glob, "max_results": 5},
                )

                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "SECRET_PATH_DENIED")

    async def test_search_text_literal_mode_passes_fixed_strings_to_ripgrep(self) -> None:
        snapshot_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/app.py", b"needle\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/app.py",
                    "backend",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:d29210777777dac0b3d12f6a656a073c9ba717cf6932dbc01b0cc6dc1e7779b8",
                    line_count=1,
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=LocalSourceCache(root_dir=Path(tmpdir)),
                permission_engine=PermissionEngine(),
            )
            with patch("backend.execution._run_ripgrep_json") as run_mock:
                run_mock.return_value = ("", False, 1, "")
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(),
                        agent_id=new_uuid7(),
                        snapshot_id=snapshot_id,
                    ),
                    "search_text",
                    {"query": "a.b", "mode": "literal", "path_prefix": "backend/", "max_results": 5},
                )

        self.assertTrue(result["ok"])
        argv = run_mock.call_args.args[0]
        self.assertIn("--fixed-strings", argv)

    async def test_search_text_supports_path_glob_cursor_and_next_cursor(self) -> None:
        snapshot_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/app.py", b"needle\n", content_type="text/plain")
        storage.put_bytes("blob/routes.py", b"needle\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/app.py",
                    "backend",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:d29210777777dac0b3d12f6a656a073c9ba717cf6932dbc01b0cc6dc1e7779b8",
                    line_count=1,
                ),
                _file(
                    "backend/routes.py",
                    "backend",
                    "routes.py",
                    "file",
                    content_key="blob/routes.py",
                    content_hash="sha256:d29210777777dac0b3d12f6a656a073c9ba717cf6932dbc01b0cc6dc1e7779b8",
                    line_count=1,
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LocalSourceCache(root_dir=Path(tmpdir))
            first = cache.file_path(snapshot_id, "backend/app.py")
            second = cache.file_path(snapshot_id, "backend/routes.py")
            output = "\n".join(
                [
                    json.dumps(
                        {
                            "type": "match",
                            "data": {
                                "path": {"text": str(first)},
                                "line_number": 1,
                                "lines": {"text": "needle\n"},
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "match",
                            "data": {
                                "path": {"text": str(second)},
                                "line_number": 1,
                                "lines": {"text": "needle\n"},
                            },
                        }
                    ),
                ]
            )
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=cache,
                permission_engine=PermissionEngine(),
                search_config=SearchTextToolConfig(max_results=10, timeout_seconds=5, max_output_bytes=65536),
            )
            with patch("backend.execution._run_ripgrep_json") as run_mock:
                run_mock.return_value = (output, False, 0, "")
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(),
                        agent_id=new_uuid7(),
                        snapshot_id=snapshot_id,
                    ),
                    "search_text",
                    {
                        "query": "needle",
                        "mode": "literal",
                        "path_prefix": "backend/",
                        "path_glob": "**/*.py",
                        "max_results": 1,
                        "cursor": "1",
                    },
                )

        self.assertTrue(result["ok"])
        self.assertEqual([match["path"] for match in result["result"]["matches"]], ["backend/routes.py"])
        self.assertIsNone(result["next_cursor"])
        argv = run_mock.call_args.args[0]
        self.assertIn("-g", argv)
        self.assertEqual(argv[argv.index("-g") + 1], "**/*.py")

    async def test_search_text_cursor_can_page_multiple_matches_in_one_file(self) -> None:
        snapshot_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/app.py", b"needle one\nneedle two\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/app.py",
                    "backend",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:app",
                    line_count=2,
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=LocalSourceCache(root_dir=Path(tmpdir)),
                permission_engine=PermissionEngine(),
                search_config=SearchTextToolConfig(max_results=10, timeout_seconds=5, max_output_bytes=65536),
            )
            context = ToolExecutionContext(
                tool_call_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=snapshot_id,
            )
            first_page = await executor.execute(
                context,
                "search_text",
                {"query": "needle", "mode": "literal", "path_prefix": "backend/", "max_results": 1},
            )
            second_page = await executor.execute(
                context,
                "search_text",
                {
                    "query": "needle",
                    "mode": "literal",
                    "path_prefix": "backend/",
                    "max_results": 1,
                    "cursor": first_page["next_cursor"],
                },
            )

        self.assertTrue(first_page["ok"])
        self.assertEqual(first_page["result"]["matches"][0]["line_number"], 1)
        self.assertEqual(first_page["next_cursor"], "1")
        self.assertTrue(second_page["ok"])
        self.assertEqual(second_page["result"]["matches"][0]["line_number"], 2)
        self.assertIsNone(second_page["next_cursor"])

    async def test_search_text_returns_recoverable_error_when_ripgrep_is_missing(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        with patch("backend.execution._run_ripgrep_json", side_effect=FileNotFoundError("rg")):
            result = await executor.execute(
                ToolExecutionContext(
                    tool_call_id=new_uuid7(),
                    agent_id=new_uuid7(),
                    snapshot_id=new_uuid7(),
                ),
                "search_text",
                {"query": "FastAPI", "path_prefix": "", "max_results": 5},
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SEARCH_BACKEND_UNAVAILABLE")
        self.assertTrue(result["error"]["retryable"])

    async def test_search_text_returns_recoverable_error_on_ripgrep_failure(self) -> None:
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        with patch("backend.execution._run_ripgrep_json") as run_mock:
            run_mock.return_value = ("", False, 2, "rg: regex parse error\n")
            result = await executor.execute(
                ToolExecutionContext(
                    tool_call_id=new_uuid7(),
                    agent_id=new_uuid7(),
                    snapshot_id=new_uuid7(),
                ),
                "search_text",
                {"query": "[", "path_prefix": "", "max_results": 5},
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SEARCH_TEXT_FAILED")
        self.assertIn("regex parse error", result["error"]["message"])

    async def test_search_text_ignores_truncated_partial_json_line(self) -> None:
        snapshot_id = new_uuid7()
        storage = InMemoryObjectStorage()
        storage.put_bytes("blob/app.py", b"needle\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/api/app.py",
                    "backend/api",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:d29210777777dac0b3d12f6a656a073c9ba717cf6932dbc01b0cc6dc1e7779b8",
                    line_count=1,
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = LocalSourceCache(root_dir=Path(tmpdir))
            match_path = root.file_path(snapshot_id, "backend/api/app.py")
            output = "\n".join(
                [
                    json.dumps(
                        {
                            "type": "match",
                            "data": {
                                "path": {"text": str(match_path)},
                                "line_number": 1,
                                "lines": {"text": "needle\n"},
                            },
                        }
                    ),
                    '{"type":"match"',
                ]
            )
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=root,
                permission_engine=PermissionEngine(),
                search_config=SearchTextToolConfig(max_results=10, timeout_seconds=5, max_output_bytes=len(output)),
            )

            with patch("backend.execution._run_ripgrep_json") as run_mock:
                run_mock.return_value = (output + "truncated", True, 0, "")
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(),
                        agent_id=new_uuid7(),
                        snapshot_id=snapshot_id,
                    ),
                    "search_text",
                    {"query": "needle", "path_prefix": "backend/", "max_results": 5},
                )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["result"]["matches"]), 1)
        self.assertTrue(result["truncated"])

    async def test_read_file_redownloads_cache_entry_when_content_hash_does_not_match(self) -> None:
        snapshot_id = new_uuid7()
        storage = InMemoryObjectStorage()
        storage.put_bytes("blob/app.py", b"fresh\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/api/app.py",
                    "backend/api",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:02db0d2659c9d48bc15f81a388594fc0e3cf4c780fdc27ea21e0671afc37de19",
                    line_count=1,
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LocalSourceCache(root_dir=Path(tmpdir))
            cache.write_file(snapshot_id, "backend/api/app.py", b"stale\n")
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=cache,
                permission_engine=PermissionEngine(),
            )
            result = await executor.execute(
                ToolExecutionContext(
                    tool_call_id=new_uuid7(),
                    agent_id=new_uuid7(),
                    snapshot_id=snapshot_id,
                ),
                "read_file",
                {"path": "backend/api/app.py", "start_line": 1, "end_line": 1},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["content"], "fresh\n")

    async def test_search_text_rejects_prefix_that_exceeds_cache_limit_before_downloading(self) -> None:
        snapshot_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/a.py", b"a" * 6, content_type="text/plain")
        storage.put_bytes("blob/b.py", b"b" * 6, content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/a.py",
                    "backend",
                    "a.py",
                    "file",
                    content_key="blob/a.py",
                    content_hash="sha256:" + "0" * 64,
                    size_bytes=6,
                ),
                _file(
                    "backend/b.py",
                    "backend",
                    "b.py",
                    "file",
                    content_key="blob/b.py",
                    content_hash="sha256:" + "0" * 64,
                    size_bytes=6,
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=LocalSourceCache(root_dir=Path(tmpdir)),
                permission_engine=PermissionEngine(),
                cache_config=CacheConfig(max_prefix_bytes=10),
            )
            result = await executor.execute(
                ToolExecutionContext(
                    tool_call_id=new_uuid7(),
                    agent_id=new_uuid7(),
                    snapshot_id=snapshot_id,
                ),
                "search_text",
                {"query": "a", "path_prefix": "backend/", "max_results": 5},
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CACHE_PREFIX_TOO_LARGE")
        self.assertEqual(storage.requested_keys, [])

    async def test_search_text_materializes_prefix_under_cache_lock(self) -> None:
        snapshot_id = new_uuid7()
        storage = CountingStorage()
        storage.put_bytes("blob/app.py", b"needle\n", content_type="text/plain")
        repository = FakeToolRepository(
            files=[
                _file(
                    "backend/app.py",
                    "backend",
                    "app.py",
                    "file",
                    content_key="blob/app.py",
                    content_hash="sha256:d29210777777dac0b3d12f6a656a073c9ba717cf6932dbc01b0cc6dc1e7779b8",
                    line_count=1,
                    size_bytes=7,
                )
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = SpyLocalSourceCache(root_dir=Path(tmpdir))
            executor = SourceToolExecutor(
                repository=repository,
                storage=storage,
                cache=cache,
                permission_engine=PermissionEngine(),
            )
            with patch("backend.execution._run_ripgrep_json") as run_mock:
                run_mock.return_value = ("", False, 1, "")
                result = await executor.execute(
                    ToolExecutionContext(
                        tool_call_id=new_uuid7(),
                        agent_id=new_uuid7(),
                        snapshot_id=snapshot_id,
                    ),
                    "search_text",
                    {"query": "needle", "path_prefix": "backend/", "max_results": 5},
                )

        self.assertTrue(result["ok"])
        self.assertEqual(cache.locked_prefixes, [(snapshot_id, "backend/")])

    async def test_execution_handler_publishes_denied_tool_call_when_policy_denies(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "../secret.txt"},
                "status": "queued",
            }
        )
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(repository.started, [tool_call_id])
        self.assertEqual(repository.completed, [])
        self.assertEqual(repository.failed[0]["tool_call_id"], tool_call_id)
        self.assertEqual(repository.failed[0]["status"], "denied")
        self.assertEqual(repository.failed[0]["permission_decision"], "deny")
        self.assertFalse(repository.failed[0]["result"]["ok"])
        self.assertEqual(repository.failed[0]["result"]["error"]["code"], "UNSAFE_PATH")
        self.assertEqual(repository.stream_events[0]["event_type"], "tool_result")
        self.assertEqual(repository.outbox_events[0].event_type, EventType.TOOL_CALL_DENIED)
        self.assertEqual(repository.outbox_events[0].payload["tool_call_id"], str(tool_call_id))
        self.assertEqual(repository.outbox_events[0].payload["error"]["code"], "UNSAFE_PATH")

    async def test_execution_handler_publishes_failed_tool_call_when_tool_returns_error(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "search_text",
                "arguments_json": {"query": "[", "path_prefix": "", "max_results": 5},
                "status": "queued",
            }
        )
        executor = StaticExecutor(
            {
                "ok": False,
                "tool_name": "search_text",
                "error": {
                    "code": "SEARCH_TEXT_FAILED",
                    "message": "ripgrep failed",
                    "retryable": True,
                },
            }
        )

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(repository.completed, [])
        self.assertEqual(repository.failed[0]["tool_call_id"], tool_call_id)
        self.assertEqual(repository.failed[0]["status"], "failed")
        self.assertEqual(repository.failed[0]["permission_decision"], "allow")
        self.assertEqual(repository.failed[0]["error_code"], "SEARCH_TEXT_FAILED")
        self.assertEqual(repository.stream_events[0]["event_type"], "tool_result")
        self.assertEqual(repository.outbox_events[0].event_type, EventType.TOOL_CALL_FAILED)
        self.assertEqual(repository.outbox_events[0].payload["error"]["message"], "ripgrep failed")

    async def test_execution_handler_retries_when_tool_call_cannot_be_claimed_or_replayed(self) -> None:
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(queued_tool_call=None)
        executor = CountingExecutor()

        with self.assertRaisesRegex(RuntimeError, "not terminal"):
            await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
                EventEnvelope.new(
                    event_type=EventType.TOOL_CALL_REQUESTED,
                    analysis_id=new_uuid7(),
                    agent_id=new_uuid7(),
                    snapshot_id=new_uuid7(),
                    payload={"tool_call_id": str(tool_call_id)},
                )
            )

        self.assertEqual(executor.calls, 0)
        self.assertEqual(repository.started, [])
        self.assertEqual(repository.completed, [])

    async def test_execution_handler_retries_non_terminal_claimed_tool_call(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call=None,
            existing_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "status": "running",
                "result_summary": None,
                "error_code": None,
                "error_message": None,
            },
        )
        executor = CountingExecutor()

        with self.assertRaisesRegex(RuntimeError, "not terminal"):
            await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
                EventEnvelope.new(
                    event_type=EventType.TOOL_CALL_REQUESTED,
                    analysis_id=analysis_id,
                    agent_id=agent_id,
                    snapshot_id=snapshot_id,
                    payload={"tool_call_id": str(tool_call_id)},
                )
            )

        self.assertEqual(executor.calls, 0)
        self.assertEqual(repository.outbox_events, [])

    async def test_execution_handler_republishes_completed_tool_call_on_replay(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call=None,
            existing_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "status": "completed",
                "result_summary": '{"ok":true}',
                "error_code": None,
                "error_message": None,
            },
        )
        executor = CountingExecutor()

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(executor.calls, 0)
        self.assertEqual(repository.outbox_events[0].event_type, EventType.TOOL_CALL_COMPLETED)
        self.assertEqual(repository.outbox_events[0].payload["tool_call_id"], str(tool_call_id))

    async def test_execution_handler_cancels_claimed_tool_call_without_executing_when_analysis_is_cancelled(
        self,
    ) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "status": "queued",
            },
            analysis_status="cancelled",
        )
        executor = CountingExecutor()

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(executor.calls, 0)
        self.assertEqual(repository.failed[0]["status"], "cancelled")
        self.assertEqual(repository.failed[0]["error_code"], "TOOL_CALL_CANCELLED")
        self.assertEqual(repository.stream_events[0]["event_type"], "tool_result")
        self.assertEqual(repository.outbox_events[0].event_type, EventType.TOOL_CALL_FAILED)
        self.assertEqual(repository.outbox_events[0].payload["error"]["code"], "TOOL_CALL_CANCELLED")

    async def test_execution_handler_uses_atomic_finalize_when_repository_supports_it(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "status": "queued",
            },
            supports_atomic_finalize=True,
        )
        executor = StaticExecutor({"ok": True, "tool_name": "read_file", "result": {"content": "ok"}})

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(repository.completed, [])
        self.assertEqual(repository.stream_events, [])
        self.assertEqual(repository.outbox_events, [])
        self.assertEqual(repository.finalized[0]["claim_owner"], repository.claim_owner)
        self.assertEqual(repository.finalized[0]["status"], "completed")
        self.assertEqual(repository.finalized[0]["event"].event_type, EventType.TOOL_CALL_COMPLETED)
        self.assertEqual(repository.finalized[0]["event"].payload["tool_call_id"], str(tool_call_id))

    async def test_execution_handler_renews_tool_call_lease_while_executor_runs(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "status": "queued",
            },
            supports_atomic_finalize=True,
        )
        executor = AwaitingExecutor({"ok": True, "tool_name": "read_file", "result": {"content": "ok"}})

        await ExecutionCommandHandler(
            tool_calls=repository,
            executor=executor,
            heartbeat_interval_seconds=0,
        )(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertGreaterEqual(len(repository.renewed), 1)
        self.assertEqual(repository.renewed[0]["tool_call_id"], tool_call_id)
        self.assertEqual(repository.renewed[0]["claim_owner"], repository.claim_owner)

    async def test_execution_handler_releases_claim_when_executor_raises(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "status": "queued",
            },
            supports_atomic_finalize=True,
        )
        executor = RaisingExecutor(RuntimeError("storage unavailable"))

        with self.assertRaisesRegex(RuntimeError, "storage unavailable"):
            await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
                EventEnvelope.new(
                    event_type=EventType.TOOL_CALL_REQUESTED,
                    analysis_id=analysis_id,
                    agent_id=agent_id,
                    snapshot_id=snapshot_id,
                    payload={"tool_call_id": str(tool_call_id)},
                )
            )

        self.assertEqual(repository.released, [{"tool_call_id": tool_call_id, "claim_owner": repository.claim_owner}])
        self.assertEqual(repository.finalized, [])
        self.assertEqual(repository.outbox_events, [])

    async def test_execution_handler_releases_claim_when_atomic_finalize_raises(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "status": "queued",
            },
            supports_atomic_finalize=True,
            finalize_exception=RuntimeError("database unavailable"),
        )
        executor = StaticExecutor({"ok": True, "tool_name": "read_file", "result": {"content": "ok"}})

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
                EventEnvelope.new(
                    event_type=EventType.TOOL_CALL_REQUESTED,
                    analysis_id=analysis_id,
                    agent_id=agent_id,
                    snapshot_id=snapshot_id,
                    payload={"tool_call_id": str(tool_call_id)},
                )
            )

        self.assertEqual(repository.released, [{"tool_call_id": tool_call_id, "claim_owner": repository.claim_owner}])

    async def test_execution_handler_persists_result_ref_from_tool_result(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "status": "queued",
            },
            supports_atomic_finalize=True,
        )
        executor = StaticExecutor(
            {
                "ok": True,
                "tool_name": "read_file",
                "result": {"content": "ok"},
                "result_ref": f"tool-results/{tool_call_id}.json",
            }
        )

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(repository.finalized[0]["result_ref"], f"tool-results/{tool_call_id}.json")

    async def test_execution_handler_does_not_publish_tool_result_when_finalize_is_rejected_after_cancel(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
                "status": "queued",
            },
            supports_atomic_finalize=True,
            finalize_result=False,
        )
        executor = StaticExecutor({"ok": True, "tool_name": "read_file", "result": {"content": "ok"}})

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(repository.finalized[0]["status"], "completed")
        self.assertEqual(repository.stream_events, [])
        self.assertEqual(repository.outbox_events, [])

    async def test_execution_handler_uses_tool_registry_from_config_snapshot(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "search_text",
                "arguments_json": {"query": "FastAPI", "path_prefix": "", "max_results": 5},
                "status": "queued",
                "config_json": {
                    "tools": {
                        "enabled": ["read_file"],
                        "read_file": {"default_lines": 20, "max_lines": 40, "max_bytes": 8192},
                        "search_text": {"max_results": 5, "timeout_seconds": 2, "max_output_bytes": 1024},
                    }
                },
            }
        )
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
        )

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(repository.completed, [])
        self.assertEqual(repository.failed[0]["status"], "denied")
        self.assertEqual(repository.failed[0]["result"]["error"]["code"], "TOOL_NOT_ENABLED")
        self.assertIn("not enabled", repository.failed[0]["result"]["error"]["message"])
        self.assertEqual(repository.outbox_events[0].event_type, EventType.TOOL_CALL_DENIED)

    async def test_execution_handler_uses_web_search_limits_from_config_snapshot(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        client = FakeTavilyClient({"results": []})
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "web_search",
                "arguments_json": {"query": "deepdive", "max_results": 10},
                "status": "queued",
                "config_json": {
                    "tools": {
                        "enabled": ["web_search"],
                        "web_search": {"max_results": 3, "timeout_seconds": 9, "max_query_chars": 400},
                    }
                },
            }
        )
        executor = SourceToolExecutor(
            repository=FakeToolRepository(files=[]),
            storage=InMemoryObjectStorage(),
            cache=LocalSourceCache(root_dir=Path(tempfile.mkdtemp())),
            permission_engine=PermissionEngine(),
            web_search_config=WebSearchToolConfig(max_results=10),
            tavily_api_key="tvly-test-key",
            tavily_client=client,
        )

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(client.requests[0]["max_results"], 3)
        self.assertEqual(repository.completed[0]["result"]["ok"], True)

    async def test_execution_handler_passes_analysis_id_to_executor_context(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "openai_call_id": "call_1",
                "tool_name": "document_create",
                "arguments_json": {"title": "Notes", "content": "draft"},
                "status": "queued",
            }
        )
        executor = ContextCapturingExecutor(
            {"ok": True, "tool_name": "document_create", "result": {"document_id": "doc_1"}}
        )

        await ExecutionCommandHandler(tool_calls=repository, executor=executor)(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(executor.contexts[0].analysis_id, analysis_id)
        self.assertEqual(executor.contexts[0].agent_id, agent_id)
        self.assertEqual(executor.contexts[0].snapshot_id, snapshot_id)


class PostgresToolCallRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_claim_queued_tool_call_can_take_over_expired_running_claim(self) -> None:
        tool_call_id = new_uuid7()
        connection = FakeConnection(
            rows=[
                {
                    "id": tool_call_id,
                    "agent_id": new_uuid7(),
                    "snapshot_id": new_uuid7(),
                    "openai_call_id": "call_1",
                    "tool_name": "read_file",
                    "arguments_json": {"path": "README.md"},
                    "status": "running",
                    "config_json": {},
                }
            ]
        )
        repository = PostgresToolCallRepository(connection)

        row = await repository.claim_queued_tool_call(tool_call_id)

        self.assertEqual(row["id"], tool_call_id)
        self.assertEqual(row["id"], tool_call_id)
        statement = str(connection.executed[0][0])
        params = connection.executed[0][1]
        self.assertIn("claim_expires_at < :now", statement)
        self.assertIn("claim_expires_at = :claim_expires_at", statement)
        self.assertIn("claim_owner = :claim_owner", statement)
        self.assertNotIn("permission_decision = 'allow'", statement)
        self.assertIn("status = 'queued'", statement)
        self.assertIn("status = 'running'", statement)
        self.assertIsInstance(params["claim_owner"], str)
        self.assertGreater(len(params["claim_owner"]), 20)

    async def test_finalize_tool_call_updates_result_ref(self) -> None:
        turn_id = new_uuid7()
        connection = FakeConnection(
            rows=[{"turn_id": turn_id, "openai_call_id": "call_1"}],
            scalar_values=[None, 1, None, 2],
        )
        repository = PostgresToolCallRepository(connection)
        tool_call_id = new_uuid7()
        agent_id = new_uuid7()

        await repository.finalize_tool_call(
            analysis_id=new_uuid7(),
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            status="completed",
            result={"ok": True, "result_ref": f"tool-results/{tool_call_id}.json"},
            result_ref=f"tool-results/{tool_call_id}.json",
            duration_ms=1,
            permission_decision="allow",
            error_code=None,
            error_message=None,
            claim_owner="owner-1",
            event=EventEnvelope.new(
                event_type=EventType.TOOL_CALL_COMPLETED, payload={"tool_call_id": str(tool_call_id)}
            ),
        )

        update_sql = str(connection.executed[0][0])
        update_params = connection.executed[0][1]
        self.assertIn("result_ref = :result_ref", update_sql)
        self.assertIn("claim_expires_at = NULL", update_sql)
        self.assertIn("claim_owner = NULL", update_sql)
        self.assertIn("claim_owner = :claim_owner", update_sql)
        self.assertEqual(update_params["result_ref"], f"tool-results/{tool_call_id}.json")
        self.assertEqual(update_params["claim_owner"], "owner-1")

    async def test_finalize_tool_call_appends_function_output_context_item_through_shared_store(self) -> None:
        turn_id = new_uuid7()
        connection = FakeConnection(
            rows=[{"turn_id": turn_id, "openai_call_id": "call_1"}],
            scalar_values=[None, 2],
        )
        repository = PostgresToolCallRepository(connection)
        tool_call_id = new_uuid7()
        agent_id = new_uuid7()

        await repository.finalize_tool_call(
            analysis_id=new_uuid7(),
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            status="completed",
            result={"ok": True, "result_ref": f"tool-results/{tool_call_id}.json"},
            result_ref=f"tool-results/{tool_call_id}.json",
            duration_ms=1,
            permission_decision="allow",
            error_code=None,
            error_message=None,
            claim_owner="owner-1",
            event=EventEnvelope.new(
                event_type=EventType.TOOL_CALL_COMPLETED, payload={"tool_call_id": str(tool_call_id)}
            ),
        )

        context_insert = _first_executed_params(connection, "INSERT INTO agent_context_items")
        self.assertEqual(context_insert["agent_id"], agent_id)
        self.assertEqual(context_insert["turn_id"], turn_id)
        self.assertEqual(context_insert["item_type"], "function_call_output")
        self.assertEqual(context_insert["payload_json"]["call_id"], "call_1")
        self.assertIn(f"tool-results/{tool_call_id}.json", context_insert["payload_json"]["output"])
        self.assertEqual(context_insert["idempotency_key"], "tool:function_call_output:call_1")

    async def test_finalize_tool_call_binds_claim_owner_as_text(self) -> None:
        connection = FakeConnection(rows=[], scalar_values=[None, 1])
        repository = PostgresToolCallRepository(connection)

        await repository.finalize_tool_call(
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            tool_call_id=new_uuid7(),
            status="completed",
            result={"ok": True},
            result_ref=None,
            duration_ms=1,
            permission_decision="allow",
            error_code=None,
            error_message=None,
            claim_owner="owner-1",
            event=EventEnvelope.new(event_type=EventType.TOOL_CALL_COMPLETED, payload={}),
        )

        update_statement = connection.executed[0][0]
        claim_owner_bind = update_statement._bindparams["claim_owner"]
        self.assertEqual(claim_owner_bind.type.python_type, str)

    async def test_terminal_tool_call_updates_do_not_overwrite_cancelled_rows(self) -> None:
        connection = FakeConnection(rows=[], scalar_values=[None, 1])
        repository = PostgresToolCallRepository(connection)

        await repository.finalize_tool_call(
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            tool_call_id=new_uuid7(),
            status="completed",
            result={"ok": True},
            result_ref=None,
            duration_ms=1,
            permission_decision="allow",
            error_code=None,
            error_message=None,
            claim_owner="owner-1",
            event=EventEnvelope.new(event_type=EventType.TOOL_CALL_COMPLETED, payload={}),
        )

        update_sql = str(connection.executed[0][0])
        self.assertIn("status <> 'cancelled'", update_sql)

    async def test_finalize_tool_call_does_not_emit_stream_or_outbox_when_cancelled_row_was_not_updated(self) -> None:
        connection = FakeConnection(rows=[], scalar_values=[None, 1], rowcounts=[0])
        repository = PostgresToolCallRepository(connection)

        finalized = await repository.finalize_tool_call(
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            tool_call_id=new_uuid7(),
            status="completed",
            result={"ok": True},
            result_ref=None,
            duration_ms=1,
            permission_decision="allow",
            error_code=None,
            error_message=None,
            claim_owner="owner-1",
            event=EventEnvelope.new(event_type=EventType.TOOL_CALL_COMPLETED, payload={}),
        )

        self.assertFalse(finalized)
        executed_sql = "\n".join(str(statement) for statement, _ in connection.executed)
        self.assertIn("UPDATE tool_calls", executed_sql)
        self.assertNotIn("INSERT INTO agent_stream_events", executed_sql)
        self.assertNotIn("INSERT INTO outbox_events", executed_sql)

    async def test_get_analysis_status_reads_analysis_status_for_tool_call_execution(self) -> None:
        connection = FakeConnection(rows=[{"status": "cancelled"}])
        repository = PostgresToolCallRepository(connection)

        status = await repository.get_analysis_status(new_uuid7())

        self.assertEqual(status, "cancelled")
        self.assertIn("FROM analyses", str(connection.executed[0][0]))

    async def test_renew_tool_call_claim_extends_only_matching_owner(self) -> None:
        tool_call_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": tool_call_id}])
        repository = PostgresToolCallRepository(connection)

        renewed = await repository.renew_tool_call_claim(tool_call_id=tool_call_id, claim_owner="owner-1")

        self.assertTrue(renewed)
        statement = str(connection.executed[0][0])
        params = connection.executed[0][1]
        self.assertIn("claim_owner = :claim_owner", statement)
        self.assertIn("status = 'running'", statement)
        self.assertIn("claim_expires_at = :claim_expires_at", statement)
        self.assertEqual(params["claim_owner"], "owner-1")

    async def test_release_tool_call_claim_requeues_only_matching_owner(self) -> None:
        tool_call_id = new_uuid7()
        connection = FakeConnection(rows=[{"id": tool_call_id}])
        repository = PostgresToolCallRepository(connection)

        released = await repository.release_tool_call_claim(tool_call_id=tool_call_id, claim_owner="owner-1")

        self.assertTrue(released)
        statement = str(connection.executed[0][0])
        params = connection.executed[0][1]
        self.assertIn("status = 'queued'", statement)
        self.assertIn("claim_owner = NULL", statement)
        self.assertIn("claim_owner = :claim_owner", statement)
        self.assertIn("status = 'running'", statement)
        self.assertEqual(params["claim_owner"], "owner-1")

    async def test_cancelled_claimed_tool_call_finalizes_with_claim_owner(self) -> None:
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        snapshot_id = new_uuid7()
        tool_call_id = new_uuid7()
        repository = FakeToolCallRepository(
            queued_tool_call={
                "id": tool_call_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot_id,
                "tool_name": "read_file",
                "arguments_json": {"path": "README.md"},
            },
            supports_atomic_finalize=True,
            analysis_status="cancelled",
        )
        handler = ExecutionCommandHandler(
            tool_calls=repository,
            executor=StaticExecutor({"ok": True, "tool_name": "read_file"}),
        )

        await handler(
            EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                payload={"tool_call_id": str(tool_call_id)},
            )
        )

        self.assertEqual(repository.finalized[0]["status"], "cancelled")
        self.assertEqual(repository.finalized[0]["claim_owner"], repository.claim_owner)


class PostgresSnapshotToolRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_glob_like_pattern_escapes_sql_wildcards(self) -> None:
        connection = FakeConnection()
        repository = __import__(
            "backend.execution.repository", fromlist=["PostgresSnapshotToolRepository"]
        ).PostgresSnapshotToolRepository(connection)

        await repository.search_files(new_uuid7(), query="env", max_results=10, glob="config/_secret%.env", cursor=None)

        sql = str(connection.executed[-1][0])
        params = connection.executed[-1][1]
        self.assertIn("ESCAPE '\\'", sql)
        self.assertEqual(params["glob_pattern"], "config/\\_secret\\%.env")

    async def test_search_file_query_escapes_sql_wildcards(self) -> None:
        connection = FakeConnection()
        repository = __import__(
            "backend.execution.repository", fromlist=["PostgresSnapshotToolRepository"]
        ).PostgresSnapshotToolRepository(connection)

        await repository.search_files(new_uuid7(), query="%_secret", max_results=10, glob=None, cursor=None)

        sql = str(connection.executed[-1][0])
        params = connection.executed[-1][1]
        self.assertIn("lower(path) LIKE :query ESCAPE '\\'", sql)
        self.assertEqual(params["query"], "%\\%\\_secret%")

    async def test_text_files_under_prefix_escapes_sql_wildcards(self) -> None:
        connection = FakeConnection()
        repository = __import__(
            "backend.execution.repository", fromlist=["PostgresSnapshotToolRepository"]
        ).PostgresSnapshotToolRepository(connection)

        await repository.text_files_under_prefix(new_uuid7(), "src/%_secret/")

        sql = str(connection.executed[-1][0])
        params = connection.executed[-1][1]
        self.assertIn("path LIKE :prefix ESCAPE '\\'", sql)
        self.assertEqual(params["prefix"], "src/\\%\\_secret/%")

    async def test_text_files_under_prefix_excludes_git_directory(self) -> None:
        connection = FakeConnection()
        repository = __import__(
            "backend.execution.repository", fromlist=["PostgresSnapshotToolRepository"]
        ).PostgresSnapshotToolRepository(connection)

        await repository.text_files_under_prefix(new_uuid7(), "")

        sql = str(connection.executed[-1][0])
        self.assertIn("path NOT LIKE '.git/%'", sql)
        self.assertIn("path <> '.git'", sql)

    async def test_text_files_under_prefix_excludes_secret_metadata(self) -> None:
        connection = FakeConnection()
        repository = __import__(
            "backend.execution.repository", fromlist=["PostgresSnapshotToolRepository"]
        ).PostgresSnapshotToolRepository(connection)

        await repository.text_files_under_prefix(new_uuid7(), "")

        sql = str(connection.executed[-1][0])
        self.assertIn("path <> '.env'", sql)
        self.assertIn("path <> '.git-credentials'", sql)
        self.assertIn("lower(path) NOT LIKE '%.pem'", sql)
        self.assertIn("lower(path) NOT LIKE '%service-account%.json'", sql)

    async def test_list_files_and_search_files_exclude_secret_metadata(self) -> None:
        connection = FakeConnection()
        repository = __import__(
            "backend.execution.repository", fromlist=["PostgresSnapshotToolRepository"]
        ).PostgresSnapshotToolRepository(connection)

        await repository.list_files(new_uuid7(), path="", recursive=True, max_results=10)
        list_sql = str(connection.executed[-1][0])

        await repository.search_files(new_uuid7(), query="env", max_results=10, glob=None, cursor=None)
        search_sql = str(connection.executed[-1][0])

        for sql in (list_sql, search_sql):
            self.assertIn("path <> '.git'", sql)
            self.assertIn("path NOT LIKE '.git/%'", sql)
            self.assertIn("path <> '.env'", sql)
            self.assertIn("lower(path) NOT LIKE '%.pem'", sql)

    async def test_recursive_list_files_escapes_prefix_wildcards(self) -> None:
        connection = FakeConnection()
        repository = __import__(
            "backend.execution.repository", fromlist=["PostgresSnapshotToolRepository"]
        ).PostgresSnapshotToolRepository(connection)

        await repository.list_files(new_uuid7(), path="src/%_secret", recursive=True, max_results=10)

        sql = str(connection.executed[-1][0])
        params = connection.executed[-1][1]
        self.assertIn("path LIKE :prefix ESCAPE '\\'", sql)
        self.assertEqual(params["prefix"], "src/\\%\\_secret/%")


def _file(
    path: str,
    parent_path: str | None,
    name: str,
    entry_kind: str,
    *,
    content_key: str | None = None,
    content_hash: str | None = None,
    line_count: int | None = None,
    size_bytes: int = 0,
) -> dict:
    return {
        "path": path,
        "parent_path": parent_path,
        "name": name,
        "entry_kind": entry_kind,
        "content_key": content_key,
        "content_hash": content_hash,
        "size_bytes": size_bytes,
        "line_count": line_count,
        "is_binary": False,
        "is_large": False,
    }


class FakeToolRepository(SnapshotToolRepository):
    def __init__(self, *, files: list[dict]) -> None:
        self.files = files
        self.evidence: list[dict] = []
        self.list_file_calls: list[dict] = []
        self.search_file_calls: list[dict] = []

    async def get_file(self, snapshot_id, path: str) -> dict | None:
        del snapshot_id
        return next((file for file in self.files if file["path"] == path), None)

    async def list_files(
        self,
        snapshot_id,
        *,
        path: str | None,
        recursive: bool,
        max_results: int,
        glob: str | None = None,
        cursor: str | None = None,
    ) -> list[dict]:
        del snapshot_id
        self.list_file_calls.append(
            {"path": path, "recursive": recursive, "max_results": max_results, "glob": glob, "cursor": cursor}
        )
        prefix = path.strip("/") if path is not None else None
        rows = [file for file in self.files if file["path"] != prefix]
        if prefix:
            rows = [file for file in rows if file["path"].startswith(prefix + "/")]
        if not recursive:
            rows = [file for file in rows if file["parent_path"] == prefix]
        if glob:
            rows = [file for file in rows if Path(file["path"]).match(glob)]
        offset = int(cursor or 0)
        rows = rows[offset:]
        return rows[:max_results]

    async def search_files(
        self, snapshot_id, *, query: str, max_results: int, glob: str | None = None, cursor: str | None = None
    ) -> list[dict]:
        del snapshot_id
        self.search_file_calls.append({"query": query, "max_results": max_results, "glob": glob, "cursor": cursor})
        rows = [file for file in self.files if query.lower() in file["path"].lower()]
        if glob:
            rows = [file for file in rows if Path(file["path"]).match(glob)]
        offset = int(cursor or 0)
        return rows[offset:][:max_results]

    async def text_files_under_prefix(self, snapshot_id, prefix: str) -> list[dict]:
        del snapshot_id
        return [
            file
            for file in self.files
            if file["entry_kind"] == "file"
            and file["content_key"]
            and file["path"].startswith(prefix)
            and not file["is_binary"]
            and not file["is_large"]
        ]

    async def add_evidence(
        self,
        *,
        agent_id,
        snapshot_id,
        tool_call_id,
        path,
        start_line,
        end_line,
        content_hash,
        snippet=None,
        snippet_ref=None,
        evidence_id=None,
    ) -> str:
        del agent_id, snapshot_id, tool_call_id, snippet
        evidence_id = str(evidence_id or new_uuid7())
        self.evidence.append(
            {
                "id": evidence_id,
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
                "content_hash": content_hash,
                "snippet_ref": snippet_ref,
                "created_at": datetime.now(UTC),
            }
        )
        return evidence_id


class FakeConnection:
    def __init__(
        self,
        *,
        rows: list[dict] | None = None,
        scalar_values: list[object] | None = None,
        rowcounts: list[int] | None = None,
    ) -> None:
        self.rows = rows or []
        self.scalar_values = list(scalar_values or [])
        self.rowcounts = list(rowcounts or [])
        self.executed = []
        self.scalar_calls = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        rowcount = self.rowcounts.pop(0) if self.rowcounts else len(self.rows)
        return FakeResult(self.rows, rowcount=rowcount)

    async def scalar(self, statement, params=None):
        self.scalar_calls.append((statement, params or {}))
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return None


class FakeResult:
    def __init__(self, rows: list[dict], *, rowcount: int | None = None) -> None:
        self._rows = rows
        self.rowcount = len(rows) if rowcount is None else rowcount

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


def _first_executed_params(connection: FakeConnection, sql_fragment: str) -> dict:
    for statement, params in connection.executed:
        if sql_fragment in str(statement):
            return params
    raise AssertionError(f"SQL fragment not executed: {sql_fragment}")


class FakeToolCallRepository:
    def __init__(
        self,
        *,
        queued_tool_call: dict | None,
        existing_tool_call: dict | None = None,
        supports_atomic_finalize: bool = False,
        analysis_status: str = "running",
        finalize_result: bool | None = None,
        finalize_exception: Exception | None = None,
    ) -> None:
        self.queued_tool_call = queued_tool_call
        self.existing_tool_call = existing_tool_call
        self.supports_atomic_finalize = supports_atomic_finalize
        self.analysis_status = analysis_status
        self.finalize_result = finalize_result
        self.finalize_exception = finalize_exception
        self.started: list = []
        self.completed: list[dict] = []
        self.failed: list[dict] = []
        self.stream_events: list[dict] = []
        self.outbox_events: list[EventEnvelope] = []
        self.finalized: list[dict] = []
        self.renewed: list[dict] = []
        self.released: list[dict] = []
        self.claim_owner = "test-claim-owner"

        if supports_atomic_finalize:
            self.finalize_tool_call = self._finalize_tool_call

    async def claim_queued_tool_call(self, tool_call_id):
        if self.queued_tool_call is None:
            return None
        if self.queued_tool_call["id"] != tool_call_id:
            return None
        self.started.append(tool_call_id)
        row = dict(self.queued_tool_call)
        row.setdefault("claim_owner", self.claim_owner)
        return row

    async def renew_tool_call_claim(self, *, tool_call_id, claim_owner):
        self.renewed.append({"tool_call_id": tool_call_id, "claim_owner": claim_owner})
        return claim_owner == self.claim_owner

    async def release_tool_call_claim(self, *, tool_call_id, claim_owner):
        self.released.append({"tool_call_id": tool_call_id, "claim_owner": claim_owner})
        return claim_owner == self.claim_owner

    async def mark_started(self, tool_call_id):
        self.started.append(tool_call_id)

    async def get_tool_call(self, tool_call_id):
        if self.existing_tool_call is None:
            return None
        if self.existing_tool_call["id"] != tool_call_id:
            return None
        return self.existing_tool_call

    async def get_analysis_status(self, analysis_id):
        del analysis_id
        return self.analysis_status

    async def mark_completed(
        self,
        *,
        tool_call_id,
        result: dict,
        result_ref=None,
        duration_ms: int,
        permission_decision: str = "allow",
    ):
        self.completed.append(
            {
                "tool_call_id": tool_call_id,
                "result": result,
                "result_ref": result_ref,
                "duration_ms": duration_ms,
                "permission_decision": permission_decision,
            }
        )

    async def mark_failed(self, **kwargs):
        self.failed.append(kwargs)

    async def add_stream_event(self, *, analysis_id, agent_id, event_type: str, payload: dict):
        self.stream_events.append(
            {
                "analysis_id": analysis_id,
                "agent_id": agent_id,
                "event_type": event_type,
                "payload": payload,
            }
        )

    async def add_outbox(self, event: EventEnvelope):
        self.outbox_events.append(event)

    async def _finalize_tool_call(
        self,
        *,
        analysis_id,
        agent_id,
        tool_call_id,
        status,
        result,
        result_ref=None,
        duration_ms,
        permission_decision,
        error_code,
        error_message,
        claim_owner=None,
        event,
    ):
        if self.finalize_exception is not None:
            raise self.finalize_exception
        self.finalized.append(
            {
                "analysis_id": analysis_id,
                "agent_id": agent_id,
                "tool_call_id": tool_call_id,
                "status": status,
                "result": result,
                "result_ref": result_ref,
                "duration_ms": duration_ms,
                "permission_decision": permission_decision,
                "error_code": error_code,
                "error_message": error_message,
                "claim_owner": claim_owner,
                "event": event,
            }
        )
        return True if self.finalize_result is None else self.finalize_result


class CountingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, context, tool_name: str, arguments: dict, **kwargs):
        del context, tool_name, arguments, kwargs
        self.calls += 1
        return {"ok": True}


class StaticExecutor:
    def __init__(self, result: dict) -> None:
        self.result = result

    async def execute(self, context, tool_name: str, arguments: dict, **kwargs):
        del context, tool_name, arguments, kwargs
        return self.result


class ContextCapturingExecutor:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.contexts = []

    async def execute(self, context, tool_name: str, arguments: dict, **kwargs):
        del tool_name, arguments, kwargs
        self.contexts.append(context)
        return self.result


class FakeTavilyClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.requests: list[dict] = []

    def search(self, request: dict, *, api_key: str, timeout_seconds: int) -> dict:
        del api_key, timeout_seconds
        self.requests.append(request)
        return self.response


class RaisingExecutor:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def execute(self, context, tool_name: str, arguments: dict, **kwargs):
        del context, tool_name, arguments, kwargs
        raise self.exc


class AwaitingExecutor:
    def __init__(self, result: dict) -> None:
        self.result = result

    async def execute(self, context, tool_name: str, arguments: dict, **kwargs):
        del context, tool_name, arguments, kwargs
        await asyncio.sleep(0)
        return self.result


class CountingStorage(InMemoryObjectStorage):
    def __init__(self) -> None:
        super().__init__()
        self.requested_keys: list[str] = []

    def get_bytes(self, key: str) -> bytes:
        self.requested_keys.append(key)
        return super().get_bytes(key)


class SpyLocalSourceCache(LocalSourceCache):
    def __init__(self, *, root_dir: Path) -> None:
        super().__init__(root_dir=root_dir)
        self.locked_prefixes: list[tuple] = []

    def prefix_lock(self, snapshot_id, prefix: str):
        self.locked_prefixes.append((snapshot_id, prefix))
        return super().prefix_lock(snapshot_id, prefix)


if __name__ == "__main__":
    unittest.main()
