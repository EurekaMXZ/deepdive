from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import date
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse
from uuid import UUID

from backend.cache import LocalSourceCache, normalize_prefix, normalize_repo_path
from backend.config import AppConfig, CacheConfig, ReadFileToolConfig, SearchTextToolConfig, WebSearchToolConfig
from backend.document import DocumentRepository, DocumentService, DocumentToolError
from backend.execution.envelopes import tool_error_envelope, tool_success_envelope
from backend.execution.permissions import (
    DEFAULT_TOOL_POLICY_HASH as DEFAULT_TOOL_POLICY_HASH,
)
from backend.execution.permissions import (
    DEFAULT_TOOL_POLICY_VERSION as DEFAULT_TOOL_POLICY_VERSION,
)
from backend.execution.permissions import (
    PermissionDecision,
    PermissionEngine,
)
from backend.execution.permissions import (
    PermissionResult as PermissionResult,
)
from backend.execution.ports import SnapshotToolRepository, ToolExecutionContext
from backend.execution.tool_registry import (
    DEFAULT_TOOL_REGISTRY_VERSION as DEFAULT_TOOL_REGISTRY_VERSION,
)
from backend.execution.tool_registry import (
    ToolCapability as ToolCapability,
)
from backend.execution.tool_registry import (
    ToolDefinition as ToolDefinition,
)
from backend.execution.tool_registry import (
    ToolRegistry as ToolRegistry,
)
from backend.execution.tool_registry import (
    is_parallel_safe_tool as is_parallel_safe_tool,
)
from backend.ids import new_uuid7
from backend.security import is_secret_path
from backend.storage import ObjectStorage, evidence_key, tool_result_key

ToolHandler = Callable[[ToolExecutionContext, str, dict[str, Any], AppConfig | None], Awaitable[dict[str, Any]]]
JsonObject = dict[str, Any]


class TavilyClient(Protocol):
    def search(self, request: JsonObject, *, api_key: str, timeout_seconds: int) -> JsonObject: ...


class ReadablePipe(Protocol):
    closed: bool

    def read1(self, size: int) -> bytes: ...

    def close(self) -> None: ...


class SourceToolExecutor:
    def __init__(
        self,
        *,
        repository: SnapshotToolRepository,
        storage: ObjectStorage,
        cache: LocalSourceCache,
        permission_engine: PermissionEngine,
        read_config: ReadFileToolConfig | None = None,
        search_config: SearchTextToolConfig | None = None,
        web_search_config: WebSearchToolConfig | None = None,
        cache_config: CacheConfig | None = None,
        tavily_api_key: str | None = None,
        tavily_client: TavilyClient | None = None,
        document_service: DocumentService | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._cache = cache
        self._permission_engine = permission_engine
        self._read_config = read_config or ReadFileToolConfig()
        self._search_config = search_config or SearchTextToolConfig()
        self._web_search_config = web_search_config or WebSearchToolConfig()
        self._cache_config = cache_config or CacheConfig()
        self._tavily_api_key = tavily_api_key if tavily_api_key is not None else os.environ.get("TAVILY_API_KEY", "")
        self._tavily_client = tavily_client or TavilySearchClient()
        self._document_service = document_service or DocumentService(repository=DocumentRepository(), storage=storage)
        document_tool_handler = self._execute_document_tool
        self._tool_handlers: dict[str, ToolHandler] = {
            "list_files": self._execute_list_files,
            "search_file": self._execute_search_file,
            "read_file": self._execute_read_file,
            "search_text": self._execute_search_text,
            "web_search": self._execute_web_search,
            "document_create": document_tool_handler,
            "document_get": document_tool_handler,
            "document_update": document_tool_handler,
            "document_delete": document_tool_handler,
            "document_finalize": document_tool_handler,
        }

    @property
    def tool_handlers(self) -> dict[str, ToolHandler]:
        return dict(self._tool_handlers)

    async def execute(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        config: AppConfig | None = None,
    ) -> dict[str, Any]:
        permission = self._permission_engine.evaluate_result(
            tool_name=tool_name, arguments=arguments, tools_config=config.tools if config else None
        )
        if permission.decision is not PermissionDecision.ALLOW:
            return _error(tool_name, permission.reason_code, permission.message)
        handler = self._tool_handlers.get(tool_name)
        if handler is None:
            return _error(tool_name, "UNKNOWN_TOOL", f"Unknown tool: {tool_name}")

        try:
            return await handler(context, tool_name, arguments, config)
        except DocumentToolError as exc:
            return _error(tool_name, exc.code, exc.message)
        except TimeoutError:
            return _error(tool_name, "WEB_SEARCH_TIMEOUT", "Web search timed out.", retryable=True)
        except ValueError as exc:
            code = "CACHE_PREFIX_TOO_LARGE" if "max_prefix_bytes" in str(exc) else "INVALID_ARGUMENTS"
            return _error(tool_name, code, str(exc))
        except FileNotFoundError as exc:
            return _error(
                tool_name, "SEARCH_BACKEND_UNAVAILABLE", f"Required command is unavailable: {exc}", retryable=True
            )
        except subprocess.TimeoutExpired:
            return _error(tool_name, "SEARCH_TEXT_TIMEOUT", "Text search timed out.", retryable=True)
        except OSError as exc:
            return _error(tool_name, "TOOL_IO_ERROR", str(exc), retryable=True)

    async def _execute_list_files(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        config: AppConfig | None,
    ) -> dict[str, Any]:
        del tool_name, config
        return await self._list_files(context, arguments)

    async def _execute_search_file(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        config: AppConfig | None,
    ) -> dict[str, Any]:
        del tool_name, config
        return await self._search_file(context, arguments)

    async def _execute_read_file(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        config: AppConfig | None,
    ) -> dict[str, Any]:
        del tool_name
        read_config = config.tools.read_file if config is not None else self._read_config
        return await self._read_file(context, arguments, read_config)

    async def _execute_search_text(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        config: AppConfig | None,
    ) -> dict[str, Any]:
        del tool_name
        search_config = config.tools.search_text if config is not None else self._search_config
        cache_config = config.cache if config is not None else self._cache_config
        return await self._search_text(context, arguments, search_config, cache_config)

    async def _execute_web_search(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        config: AppConfig | None,
    ) -> dict[str, Any]:
        del tool_name
        web_search_config = config.tools.web_search if config is not None else self._web_search_config
        return await self._web_search(context, arguments, web_search_config)

    async def _execute_document_tool(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        config: AppConfig | None,
    ) -> dict[str, Any]:
        del config
        return await self._document_tool(context, tool_name, arguments)

    async def _list_files(self, context: ToolExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path")
        if isinstance(path, str) and path:
            path = normalize_repo_path(path)
        elif not path:
            path = None
        rows = await self._repository.list_files(
            context.snapshot_id,
            path=path,
            recursive=bool(arguments.get("recursive", False)),
            max_results=_int_arg(arguments, "max_results", 100, 1, 100) + 1,
            glob=_optional_glob(arguments.get("glob")),
            cursor=_optional_cursor(arguments.get("cursor")),
        )
        rows = _visible_file_rows(rows)
        items, next_cursor = _page_rows(
            rows, max_results=_int_arg(arguments, "max_results", 100, 1, 100), cursor=arguments.get("cursor")
        )
        return self._ok_with_ref(
            context,
            "list_files",
            context.snapshot_id,
            {"items": [_file_item(row) for row in items]},
            [],
            next_cursor is not None,
            next_cursor,
        )

    async def _search_file(self, context: ToolExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", ""))
        rows = await self._repository.search_files(
            context.snapshot_id,
            query=query,
            max_results=_int_arg(arguments, "max_results", 50, 1, 100) + 1,
            glob=_optional_glob(arguments.get("glob")),
            cursor=_optional_cursor(arguments.get("cursor")),
        )
        rows = _visible_file_rows(rows)
        items, next_cursor = _page_rows(
            rows, max_results=_int_arg(arguments, "max_results", 50, 1, 100), cursor=arguments.get("cursor")
        )
        return self._ok_with_ref(
            context,
            "search_file",
            context.snapshot_id,
            {"items": [_file_item(row) for row in items]},
            [],
            next_cursor is not None,
            next_cursor,
        )

    async def _read_file(
        self, context: ToolExecutionContext, arguments: dict[str, Any], read_config: ReadFileToolConfig
    ) -> dict[str, Any]:
        path = normalize_repo_path(str(arguments["path"]))
        row = await self._repository.get_file(context.snapshot_id, path)
        if row is None:
            return _error("read_file", "PATH_NOT_FOUND", f"No file exists at {path} in this snapshot.")
        if row.get("is_binary") or row.get("is_large") or not row.get("content_key"):
            return _error("read_file", "FILE_NOT_READABLE", f"File is not readable: {path}")

        cache_path = await self._ensure_file(context.snapshot_id, row)
        start_line = _int_arg(arguments, "start_line", 1, 1, 2_000_000)
        requested_end = arguments.get("end_line")
        end_line = int(requested_end) if requested_end is not None else start_line + read_config.default_lines - 1
        if end_line < start_line:
            return _error("read_file", "INVALID_ARGUMENTS", "end_line must be greater than or equal to start_line.")
        max_end = start_line + read_config.max_lines - 1
        bounded_end = min(end_line, max_end)
        try:
            max_bytes = _int_arg(arguments, "max_bytes", read_config.max_bytes, 1, read_config.max_bytes)
        except ValueError as exc:
            return _error("read_file", "INVALID_ARGUMENTS", str(exc))

        selected, actual_end, truncated = _read_line_range(cache_path, start_line, bounded_end, max_bytes=max_bytes)
        if end_line > bounded_end:
            truncated = True
        evidence_id = new_uuid7()
        snippet_ref = evidence_key(evidence_id)
        self._storage.put_bytes(snippet_ref, selected.encode("utf-8"), content_type="text/plain; charset=utf-8")
        evidence_id_text = await self._repository.add_evidence(
            agent_id=context.agent_id,
            snapshot_id=context.snapshot_id,
            tool_call_id=context.tool_call_id,
            path=path,
            start_line=start_line,
            end_line=actual_end,
            content_hash=row.get("content_hash"),
            snippet=selected,
            snippet_ref=snippet_ref,
            evidence_id=evidence_id,
        )
        result = {
            "path": path,
            "start_line": start_line,
            "end_line": actual_end,
            "content": selected,
        }
        next_start_line = actual_end + 1 if truncated else None
        return self._ok_with_ref(
            context, "read_file", context.snapshot_id, result, [evidence_id_text], truncated, next_start_line
        )

    async def _search_text(
        self,
        context: ToolExecutionContext,
        arguments: dict[str, Any],
        search_config: SearchTextToolConfig,
        cache_config: CacheConfig,
    ) -> dict[str, Any]:
        query = str(arguments.get("query") or "")
        if not query.strip():
            return _error("search_text", "INVALID_ARGUMENTS", "search_text query must not be empty.")
        mode = str(arguments.get("mode") or "regex")
        if mode not in {"regex", "literal"}:
            return _error("search_text", "INVALID_ARGUMENTS", "search_text mode must be regex or literal.")
        prefix = normalize_prefix(arguments.get("path_prefix") or "")
        max_results = _int_arg(arguments, "max_results", search_config.max_results, 1, search_config.max_results)
        await self._ensure_prefix(context.snapshot_id, prefix, cache_config)
        root = self._cache.files_root(context.snapshot_id)
        search_root = root / Path(*prefix.strip("/").split("/")) if prefix else root
        argv = [
            "rg",
            "--json",
            "--line-number",
            "--column",
            "--hidden",
            "--no-ignore",
            "--no-ignore-global",
        ]
        context_lines = _int_arg(arguments, "context_lines", 0, 0, 5)
        if context_lines:
            argv.extend(["-C", str(context_lines)])
        if not bool(arguments.get("case_sensitive", False)):
            argv.append("-i")
        if mode == "literal":
            argv.append("--fixed-strings")
        path_glob = _optional_glob(arguments.get("path_glob"))
        if path_glob is not None:
            argv.extend(["-g", path_glob])
        argv.extend(["-e", query, "--", str(search_root)])
        output, output_truncated, returncode, stderr = await asyncio.to_thread(
            _run_ripgrep_json,
            argv,
            timeout_seconds=search_config.timeout_seconds,
            max_output_bytes=search_config.max_output_bytes,
        )
        if returncode not in {0, 1}:
            message = _trim_error_output(stderr or output or "ripgrep failed")
            return _error("search_text", "SEARCH_TEXT_FAILED", message)
        matches: list[dict[str, Any]] = []
        evidence_ids: list[str] = []
        cursor_offset = _cursor_offset(arguments.get("cursor"))
        seen_matches = 0
        for line in output.splitlines():
            try:
                event = _json_object(json.loads(line))
            except json.JSONDecodeError:
                output_truncated = True
                break
            if event is None or event.get("type") != "match":
                continue
            if seen_matches < cursor_offset:
                seen_matches += 1
                continue
            data = _json_object(event.get("data"))
            path_data = _json_object(data.get("path") if data is not None else None)
            lines_data = _json_object(data.get("lines") if data is not None else None)
            if data is None or path_data is None or lines_data is None:
                output_truncated = True
                break
            raw_path = path_data.get("text")
            raw_line_number = data.get("line_number")
            raw_text = lines_data.get("text")
            if not isinstance(raw_path, str) or not isinstance(raw_line_number, int) or not isinstance(raw_text, str):
                output_truncated = True
                break
            match_path = Path(raw_path)
            try:
                rel_path = match_path.relative_to(root).as_posix()
            except ValueError:
                return _error("search_text", "SEARCH_TEXT_FAILED", "ripgrep returned a path outside the snapshot cache")
            line_number = raw_line_number
            text = raw_text
            if len(matches) >= max_results:
                seen_matches += 1
                break
            matches.append({"path": rel_path, "line_number": line_number, "text": text.rstrip("\n")})
            evidence_id = new_uuid7()
            snippet_ref = evidence_key(evidence_id)
            self._storage.put_bytes(snippet_ref, text.encode("utf-8"), content_type="text/plain; charset=utf-8")
            evidence_ids.append(
                await self._repository.add_evidence(
                    agent_id=context.agent_id,
                    snapshot_id=context.snapshot_id,
                    tool_call_id=context.tool_call_id,
                    path=rel_path,
                    start_line=line_number,
                    end_line=line_number,
                    content_hash=None,
                    snippet=text,
                    snippet_ref=snippet_ref,
                    evidence_id=evidence_id,
                )
            )
            seen_matches += 1
        next_cursor = str(cursor_offset + len(matches)) if seen_matches > cursor_offset + len(matches) else None
        return self._ok_with_ref(
            context,
            "search_text",
            context.snapshot_id,
            {"matches": matches},
            evidence_ids,
            output_truncated or next_cursor is not None,
            next_cursor,
        )

    async def _web_search(
        self,
        context: ToolExecutionContext,
        arguments: dict[str, Any],
        web_search_config: WebSearchToolConfig,
    ) -> dict[str, Any]:
        if not self._tavily_api_key:
            return _error("web_search", "WEB_SEARCH_NOT_CONFIGURED", "Web search is not configured.")
        query = str(arguments.get("query") or "").strip()
        if not query:
            return _error("web_search", "INVALID_ARGUMENTS", "query must not be empty.")
        if len(query) > web_search_config.max_query_chars:
            return _error(
                "web_search", "INVALID_ARGUMENTS", f"query exceeds {web_search_config.max_query_chars} characters."
            )
        try:
            max_results = _bounded_int_arg(
                arguments, "max_results", web_search_config.max_results, 1, min(web_search_config.max_results, 10)
            )
            request: dict[str, Any] = {
                "query": query,
                "search_depth": _enum_arg(arguments, "search_depth", "basic", {"basic", "advanced"}),
                "max_results": max_results,
                "topic": _enum_arg(arguments, "topic", "general", {"general", "news", "finance"}),
                "include_raw_content": False,
                "include_answer": False,
                "include_images": False,
            }
            time_range = arguments.get("time_range")
            if time_range:
                request["time_range"] = _enum_arg(arguments, "time_range", "", {"day", "week", "month", "year"})
            for name in ("start_date", "end_date"):
                value = arguments.get(name)
                if value:
                    request[name] = _date_arg(value, name).isoformat()
            start_date = request.get("start_date")
            end_date = request.get("end_date")
            if isinstance(start_date, str) and isinstance(end_date, str) and start_date > end_date:
                raise ValueError("start_date must be before or equal to end_date")
            for name in ("include_domains", "exclude_domains"):
                domains = _domain_list(arguments.get(name))
                if domains:
                    request[name] = domains
        except ValueError as exc:
            return _error("web_search", "INVALID_ARGUMENTS", str(exc))

        try:
            payload = await asyncio.to_thread(
                self._tavily_client.search,
                request,
                api_key=self._tavily_api_key,
                timeout_seconds=web_search_config.timeout_seconds,
            )
        except TimeoutError:
            raise
        except OSError:
            return _error("web_search", "WEB_SEARCH_FAILED", "Web search request failed.", retryable=True)
        except Exception as exc:
            return _error(
                "web_search", "WEB_SEARCH_FAILED", _trim_error_output(str(exc) or type(exc).__name__), retryable=True
            )

        result = {
            "query": payload.get("query", query),
            "results": [_web_search_result(item) for item in _json_object_list(payload.get("results"))],
        }
        if payload.get("response_time") is not None:
            result["response_time"] = payload["response_time"]
        return self._ok_with_ref(
            context,
            "web_search",
            context.snapshot_id,
            result,
            [],
            False,
            None,
            scope={"type": "external_web", "snapshot_id": str(context.snapshot_id), "provider": "tavily"},
        )

    async def _document_tool(
        self, context: ToolExecutionContext, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        if context.analysis_id is None:
            return _error(tool_name, "INVALID_ARGUMENTS", "Document tools require analysis_id.")
        try:
            if tool_name == "document_create":
                kind = str(arguments.get("kind") or "markdown")
                if kind != "markdown":
                    return _error(tool_name, "INVALID_ARGUMENTS", "document kind must be markdown.")
                result = await self._document_service.create(
                    analysis_id=context.analysis_id,
                    agent_id=context.agent_id,
                    tool_call_id=context.tool_call_id,
                    title=str(arguments["title"]),
                    kind=kind,
                    content=str(arguments.get("content") or ""),
                )
            elif tool_name == "document_get":
                result = await self._document_service.get(
                    analysis_id=context.analysis_id,
                    document_id=UUID(str(arguments["document_id"])),
                    include_content=bool(arguments.get("include_content", False)),
                )
            elif tool_name == "document_update":
                result = await self._document_service.update(
                    analysis_id=context.analysis_id,
                    tool_call_id=context.tool_call_id,
                    document_id=UUID(str(arguments["document_id"])),
                    expected_version=int(arguments["expected_version"]),
                    content=str(arguments.get("content") or ""),
                )
            elif tool_name == "document_delete":
                result = await self._document_service.delete(
                    analysis_id=context.analysis_id,
                    tool_call_id=context.tool_call_id,
                    document_id=UUID(str(arguments["document_id"])),
                    expected_version=int(arguments["expected_version"]),
                )
            elif tool_name == "document_finalize":
                result = await self._document_service.finalize(
                    analysis_id=context.analysis_id,
                    tool_call_id=context.tool_call_id,
                    document_id=UUID(str(arguments["document_id"])),
                    expected_version=int(arguments["expected_version"]),
                )
            else:
                return _error(tool_name, "UNKNOWN_TOOL", f"Unknown tool: {tool_name}")
        except (KeyError, ValueError) as exc:
            if isinstance(exc, DocumentToolError):
                raise
            return _error(tool_name, "INVALID_ARGUMENTS", str(exc))
        return self._ok_with_ref(
            context,
            tool_name,
            context.snapshot_id,
            result,
            [],
            False,
            None,
            scope={
                "type": "analysis_artifact",
                "analysis_id": str(context.analysis_id),
                "snapshot_id": str(context.snapshot_id),
                "document_id": str(result["document_id"]) if "document_id" in result else None,
            },
        )

    def _ok_with_ref(
        self,
        context: ToolExecutionContext,
        tool_name: str,
        snapshot_id: UUID,
        result: dict[str, Any],
        evidence_ids: list[str],
        truncated: bool,
        next_cursor: Any,
        *,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = _ok(tool_name, snapshot_id, result, evidence_ids, truncated, next_cursor, scope=scope)
        result_ref = tool_result_key(context.tool_call_id)
        self._storage.put_bytes(
            result_ref,
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(),
            content_type="application/json; charset=utf-8",
        )
        payload["result_ref"] = result_ref
        return payload

    async def _ensure_file(self, snapshot_id: UUID, row: dict[str, Any]) -> Path:
        target = self._cache.file_path(snapshot_id, row["path"])
        if target.is_file() and _hash_matches(target.read_bytes(), row.get("content_hash")):
            return target
        data = await asyncio.to_thread(self._storage.get_bytes, row["content_key"])
        if not _hash_matches(data, row.get("content_hash")):
            raise ValueError(f"cached object hash does not match snapshot metadata for {row['path']}")
        return self._cache.write_file(snapshot_id, row["path"], data)

    async def _ensure_prefix(self, snapshot_id: UUID, prefix: str, cache_config: CacheConfig | None = None) -> None:
        effective_cache_config = cache_config or self._cache_config
        if self._cache.is_prefix_covered(snapshot_id, prefix):
            return
        with self._cache.prefix_lock(snapshot_id, prefix):
            if self._cache.is_prefix_covered(snapshot_id, prefix):
                return
            rows = await self._repository.text_files_under_prefix(snapshot_id, prefix)
            estimated_bytes = sum(int(row.get("size_bytes") or 0) for row in rows)
            if estimated_bytes > effective_cache_config.max_prefix_bytes:
                raise ValueError(
                    f"prefix cache would materialize {estimated_bytes} bytes, exceeding max_prefix_bytes={effective_cache_config.max_prefix_bytes}"
                )
            total = 0
            for row in rows:
                data = await asyncio.to_thread(self._storage.get_bytes, row["content_key"])
                if not _hash_matches(data, row.get("content_hash")):
                    raise ValueError(f"cached object hash does not match snapshot metadata for {row['path']}")
                self._cache.write_file(snapshot_id, row["path"], data)
                total += len(data)
            self._cache.mark_prefix_covered(snapshot_id, prefix=prefix, file_count=len(rows), bytes_written=total)


class TavilySearchClient:
    def search(self, request: dict[str, Any], *, api_key: str, timeout_seconds: int) -> dict[str, Any]:
        http_request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(request).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except TimeoutError:
            raise
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:4096]
            raise RuntimeError(f"Tavily Search API failed: {exc.code} {detail}") from exc


def _json_object(value: Any) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _json_object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in cast(list[Any], value):
        if isinstance(item, dict):
            items.append(cast(dict[str, Any], item))
    return items


def _int_arg(arguments: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = arguments.get(name, default)
    if raw_value is None:
        raw_value = default
    value = int(raw_value)
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_int_arg(arguments: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
    if maximum < minimum:
        raise ValueError(f"{name} maximum must be greater than or equal to {minimum}")
    raw_value = arguments.get(name, default)
    if raw_value is None:
        raw_value = default
    return min(max(int(raw_value), minimum), maximum)


def _enum_arg(arguments: dict[str, Any], name: str, default: str, allowed: set[str]) -> str:
    value = str(arguments.get(name) or default)
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(sorted(allowed))}")
    return value


def _domain_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("domains must be an array")
    raw_items = cast(list[Any], value)
    if len(raw_items) > 20:
        raise ValueError("domains must contain at most 20 items")
    domains: list[str] = []
    for item in raw_items:
        domain = str(item).strip().lower()
        if not _is_public_domain(domain):
            raise ValueError(f"invalid domain: {domain}")
        domains.append(domain)
    return domains


def _date_arg(value: Any, name: str) -> date:
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a YYYY-MM-DD date") from exc


def _is_public_domain(domain: str) -> bool:
    if not domain or "://" in domain or "/" in domain or domain.endswith("."):
        return False
    if domain in {"localhost", "local"} or domain.endswith(".local"):
        return False
    try:
        ip_address(domain)
        return False
    except ValueError:
        pass
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    return all(
        label and label.replace("-", "").isalnum() and not label.startswith("-") and not label.endswith("-")
        for label in labels
    )


def _web_search_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "content": str(item.get("content") or ""),
        "score": item.get("score"),
        "published_date": item.get("published_date"),
        "domain": item.get("domain") or _domain_from_url(str(item.get("url") or "")),
    }


def _domain_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    return parsed.netloc or None


def _optional_glob(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _is_unsafe_glob(text):
        raise ValueError("unsafe repository glob")
    return text.replace("\\", "/")


def _optional_cursor(value: Any) -> str | None:
    if value is None:
        return None
    return str(_cursor_offset(value))


def _cursor_offset(value: Any) -> int:
    if value is None or str(value).strip() == "":
        return 0
    offset = int(str(value))
    if offset < 0:
        raise ValueError("cursor must be non-negative")
    return offset


def _page_rows(rows: list[dict[str, Any]], *, max_results: int, cursor: Any) -> tuple[list[dict[str, Any]], str | None]:
    offset = _cursor_offset(cursor)
    if len(rows) > max_results:
        return rows[:max_results], str(offset + max_results)
    return rows, None


def _is_unsafe_glob(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return (
        normalized.startswith(("/", "//", "~", "../"))
        or ":" in normalized
        or normalized == ".."
        or "/../" in normalized
        or normalized.endswith("/..")
    )


def _file_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": row["path"],
        "type": row["entry_kind"],
        "size_bytes": row.get("size_bytes"),
        "line_count": row.get("line_count"),
        "is_binary": row.get("is_binary", False),
        "is_large": row.get("is_large", False),
    }


def _visible_file_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not is_secret_path(str(row.get("path") or ""))]


def _read_line_range(path: Path, start_line: int, end_line: int, *, max_bytes: int) -> tuple[str, int, bool]:
    selected: list[str] = []
    total_bytes = 0
    actual_end = start_line - 1
    truncated = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < start_line:
                continue
            if line_number > end_line:
                break
            encoded_len = len(line.encode())
            if selected and total_bytes + encoded_len > max_bytes:
                truncated = True
                break
            if not selected and encoded_len > max_bytes:
                line = line.encode()[:max_bytes].decode("utf-8", errors="replace")
                truncated = True
            selected.append(line)
            total_bytes += len(line.encode())
            actual_end = line_number
    return "".join(selected), actual_end, truncated


def _ok(
    tool_name: str,
    snapshot_id: UUID,
    result: dict[str, Any],
    evidence_ids: list[str],
    truncated: bool,
    next_cursor: Any,
    *,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return tool_success_envelope(tool_name, snapshot_id, result, evidence_ids, truncated, next_cursor, scope=scope)


def _error(tool_name: str, code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return tool_error_envelope(tool_name, code, message, retryable=retryable)


def _hash_matches(data: bytes, expected_hash: str | None) -> bool:
    if not expected_hash:
        return True
    if not _is_sha256_hash(expected_hash):
        return True
    return "sha256:" + hashlib.sha256(data).hexdigest() == expected_hash


def _trim_error_output(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")[:4096]


def _run_ripgrep_json(
    argv: list[str],
    *,
    timeout_seconds: int,
    max_output_bytes: int,
) -> tuple[str, bool, int, str]:
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    stderr_limit = 4096
    output_truncated = False
    lock = threading.Lock()

    def read_stdout() -> None:
        nonlocal output_truncated
        if process.stdout is None:
            return
        stdout_pipe = cast(ReadablePipe, process.stdout)
        while True:
            chunk = stdout_pipe.read1(8192)
            if not chunk:
                return
            with lock:
                remaining = max(0, max_output_bytes - len(stdout_buffer))
                if remaining:
                    stdout_buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    output_truncated = True
                    break
        if process.poll() is None:
            process.terminate()

    def read_stderr() -> None:
        if process.stderr is None:
            return
        stderr_pipe = cast(ReadablePipe, process.stderr)
        while True:
            chunk = stderr_pipe.read1(4096)
            if not chunk:
                return
            with lock:
                remaining = max(0, stderr_limit - len(stderr_buffer))
                if remaining:
                    stderr_buffer.extend(chunk[:remaining])

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        _close_pipe(process.stdout)
        _close_pipe(process.stderr)
        raise
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    _close_pipe(process.stdout)
    _close_pipe(process.stderr)
    stdout = bytes(stdout_buffer).decode("utf-8", errors="replace")
    stderr = bytes(stderr_buffer).decode("utf-8", errors="replace")
    if output_truncated and returncode not in {0, 1}:
        returncode = 0
    return stdout, output_truncated, returncode, stderr


def _close_pipe(pipe: Any) -> None:
    if pipe is not None and not pipe.closed:
        pipe.close()


def _is_sha256_hash(value: str) -> bool:
    prefix = "sha256:"
    if not value.startswith(prefix):
        return False
    digest = value[len(prefix) :]
    return len(digest) == 64 and all(char in "0123456789abcdefABCDEF" for char in digest)
