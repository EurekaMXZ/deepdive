from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from backend.config import ToolsConfig

DEFAULT_TOOL_REGISTRY_VERSION = "analysis-tools-v2"


class ToolCapability(StrEnum):
    SOURCE_READ = "source_read"
    EXTERNAL_NETWORK = "external_network"
    ARTIFACT_READ = "artifact_read"
    ARTIFACT_WRITE = "artifact_write"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    capability: ToolCapability
    read_only: bool = True
    idempotent: bool = True
    requires_analysis_id: bool = False
    parallel_safe: bool = True


TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "list_files": ToolDefinition(
        "list_files",
        "List files and directories from snapshot metadata.",
        ToolCapability.SOURCE_READ,
    ),
    "search_file": ToolDefinition(
        "search_file",
        "Search file paths from snapshot metadata.",
        ToolCapability.SOURCE_READ,
    ),
    "search_text": ToolDefinition(
        "search_text",
        "Search text content using ripgrep over a cached prefix.",
        ToolCapability.SOURCE_READ,
    ),
    "read_file": ToolDefinition(
        "read_file",
        "Read a bounded line range from one snapshot file.",
        ToolCapability.SOURCE_READ,
    ),
    "web_search": ToolDefinition(
        "web_search",
        "Search the public web through the configured Tavily Search API.",
        ToolCapability.EXTERNAL_NETWORK,
        idempotent=False,
        parallel_safe=False,
    ),
    "todo_update": ToolDefinition(
        "todo_update",
        "Update the current Codex-style analysis TODO plan snapshot.",
        ToolCapability.ARTIFACT_WRITE,
        read_only=False,
        idempotent=False,
        requires_analysis_id=True,
        parallel_safe=False,
    ),
    "document_create": ToolDefinition(
        "document_create",
        "Create one focused markdown analysis document artifact, optionally under a document tree folder.",
        ToolCapability.ARTIFACT_WRITE,
        read_only=False,
        idempotent=False,
        requires_analysis_id=True,
        parallel_safe=False,
    ),
    "document_folder_create": ToolDefinition(
        "document_folder_create",
        "Create a folder node in the analysis document tree.",
        ToolCapability.ARTIFACT_WRITE,
        read_only=False,
        idempotent=False,
        requires_analysis_id=True,
        parallel_safe=False,
    ),
    "document_get": ToolDefinition(
        "document_get",
        "Read a document artifact by id.",
        ToolCapability.ARTIFACT_READ,
        requires_analysis_id=True,
    ),
    "document_update": ToolDefinition(
        "document_update",
        "Replace a draft document artifact with new markdown content.",
        ToolCapability.ARTIFACT_WRITE,
        read_only=False,
        idempotent=False,
        requires_analysis_id=True,
        parallel_safe=False,
    ),
    "document_delete": ToolDefinition(
        "document_delete",
        "Soft-delete a draft document artifact.",
        ToolCapability.ARTIFACT_WRITE,
        read_only=False,
        idempotent=False,
        requires_analysis_id=True,
        parallel_safe=False,
    ),
    "document_finalize": ToolDefinition(
        "document_finalize",
        "Finalize a draft document artifact.",
        ToolCapability.ARTIFACT_WRITE,
        read_only=False,
        idempotent=False,
        requires_analysis_id=True,
        parallel_safe=False,
    ),
}


def is_parallel_safe_tool(tool_name: str) -> bool:
    definition = TOOL_DEFINITIONS.get(tool_name)
    return bool(definition.parallel_safe) if definition is not None else False


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_files": {
        "type": "object",
        "properties": {
            "path": {"type": ["string", "null"], "description": "Repository-relative directory path."},
            "recursive": {"type": "boolean"},
            "glob": {"type": ["string", "null"], "description": "Optional repository path glob."},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": ["string", "null"], "description": "Opaque pagination cursor from a previous result."},
        },
        "required": ["path", "recursive", "glob", "max_results", "cursor"],
        "additionalProperties": False,
    },
    "search_file": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "glob": {"type": ["string", "null"], "description": "Optional repository path glob."},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": ["string", "null"], "description": "Opaque pagination cursor from a previous result."},
        },
        "required": ["query", "glob", "max_results", "cursor"],
        "additionalProperties": False,
    },
    "search_text": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "mode": {"type": "string", "enum": ["regex", "literal"]},
            "path_prefix": {"type": "string"},
            "path_glob": {
                "type": ["string", "null"],
                "description": "Optional ripgrep path glob scoped under path_prefix.",
            },
            "case_sensitive": {"type": "boolean"},
            "context_lines": {"type": "integer", "minimum": 0, "maximum": 5},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": ["string", "null"], "description": "Opaque pagination cursor from a previous result."},
        },
        "required": [
            "query",
            "mode",
            "path_prefix",
            "path_glob",
            "case_sensitive",
            "context_lines",
            "max_results",
            "cursor",
        ],
        "additionalProperties": False,
    },
    "read_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": ["integer", "null"], "minimum": 1},
            "end_line": {"type": ["integer", "null"], "minimum": 1},
            "max_bytes": {"type": ["integer", "null"], "minimum": 1},
        },
        "required": ["path", "start_line", "end_line", "max_bytes"],
        "additionalProperties": False,
    },
    "web_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 500},
            "search_depth": {"type": "string", "enum": ["basic", "advanced"]},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            "topic": {"type": "string", "enum": ["general", "news", "finance"]},
            "time_range": {"type": ["string", "null"], "enum": ["day", "week", "month", "year", None]},
            "start_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
            "end_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
            "include_domains": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 20},
            "exclude_domains": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 20},
        },
        "required": [
            "query",
            "search_depth",
            "max_results",
            "topic",
            "time_range",
            "start_date",
            "end_date",
            "include_domains",
            "exclude_domains",
        ],
        "additionalProperties": False,
    },
    "document_create": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "kind": {"type": "string", "enum": ["markdown"]},
            "parent_node_id": {"type": ["string", "null"]},
            "slug": {"type": ["string", "null"], "minLength": 1, "maxLength": 96},
            "focus_area": {"type": ["string", "null"], "maxLength": 300},
            "sections": {
                "type": ["array", "null"],
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "stable_id": {"type": "string", "minLength": 1, "maxLength": 96},
                        "title": {"type": "string", "minLength": 1, "maxLength": 200},
                        "content": {"type": "string"},
                        "sort_order": {"type": "integer"},
                    },
                    "required": ["stable_id", "title", "content", "sort_order"],
                    "additionalProperties": False,
                },
            },
            "content": {"type": ["string", "null"]},
        },
        "required": ["title", "kind", "parent_node_id", "slug", "focus_area", "sections", "content"],
        "additionalProperties": False,
    },
    "document_folder_create": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "slug": {"type": "string", "minLength": 1, "maxLength": 96},
            "parent_node_id": {"type": ["string", "null"]},
            "sort_order": {"type": "integer"},
        },
        "required": ["title", "slug", "parent_node_id", "sort_order"],
        "additionalProperties": False,
    },
    "todo_update": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 64,
                            "description": "Stable lowercase slug for the TODO item.",
                        },
                        "title": {"type": "string", "minLength": 1, "maxLength": 80},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                    },
                    "required": ["id", "title", "status"],
                    "additionalProperties": False,
                },
            },
            "note": {"type": ["string", "null"], "maxLength": 500},
        },
        "required": ["items", "note"],
        "additionalProperties": False,
    },
    "document_get": {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "include_content": {"type": "boolean"},
            "include_sections": {"type": "boolean"},
        },
        "required": ["document_id", "include_content", "include_sections"],
        "additionalProperties": False,
    },
    "document_update": {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "expected_version": {"type": "integer", "minimum": 1},
            "sections": {
                "type": ["array", "null"],
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "stable_id": {"type": "string", "minLength": 1, "maxLength": 96},
                        "title": {"type": "string", "minLength": 1, "maxLength": 200},
                        "content": {"type": "string"},
                        "sort_order": {"type": "integer"},
                    },
                    "required": ["stable_id", "title", "content", "sort_order"],
                    "additionalProperties": False,
                },
            },
            "content": {"type": ["string", "null"]},
        },
        "required": ["document_id", "expected_version", "sections", "content"],
        "additionalProperties": False,
    },
    "document_delete": {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "expected_version": {"type": "integer", "minimum": 1},
        },
        "required": ["document_id", "expected_version"],
        "additionalProperties": False,
    },
    "document_finalize": {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "expected_version": {"type": "integer", "minimum": 1},
        },
        "required": ["document_id", "expected_version"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[ToolDefinition, ...]
    hosted_tools: tuple[dict[str, Any], ...] = ()

    @classmethod
    def default(cls) -> ToolRegistry:
        return cls.from_config(ToolsConfig())

    @classmethod
    def from_config(cls, config: ToolsConfig) -> ToolRegistry:
        unknown_tools = tuple(name for name in config.enabled if name not in TOOL_DEFINITIONS)
        if unknown_tools:
            raise ValueError(f"unknown enabled tools: {', '.join(sorted(unknown_tools))}")
        return cls(
            tools=tuple(TOOL_DEFINITIONS[name] for name in config.enabled),
            hosted_tools=tuple(cls.hosted_response_tools(config)),
        )

    def response_tools(self) -> list[dict[str, Any]]:
        function_tools = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": TOOL_SCHEMAS[tool.name],
                "strict": True,
            }
            for tool in self.tools
        ]
        return function_tools + [dict(tool) for tool in self.hosted_tools]

    @staticmethod
    def hosted_response_tools(config: ToolsConfig) -> list[dict[str, Any]]:
        web_search = config.openai_web_search
        if not web_search.enabled:
            return []
        tool: dict[str, Any] = {
            "type": "web_search",
            "search_context_size": web_search.search_context_size,
            "external_web_access": web_search.external_web_access,
        }
        filters: dict[str, list[str]] = {}
        if web_search.allowed_domains:
            filters["allowed_domains"] = list(web_search.allowed_domains)
        if web_search.blocked_domains:
            filters["blocked_domains"] = list(web_search.blocked_domains)
        if filters:
            tool["filters"] = filters
        if web_search.return_token_budget:
            tool["return_token_budget"] = web_search.return_token_budget
        return [tool]
