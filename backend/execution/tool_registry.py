from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.config import ToolsConfig


DEFAULT_TOOL_REGISTRY_VERSION = "readonly-source-tools-v1"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    read_only: bool = True


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[ToolDefinition, ...]

    @classmethod
    def default(cls) -> "ToolRegistry":
        return cls.from_config(ToolsConfig())

    @classmethod
    def from_config(cls, config: ToolsConfig) -> "ToolRegistry":
        definitions = {
            "list_files": ToolDefinition("list_files", "List files and directories from snapshot metadata."),
            "search_file": ToolDefinition("search_file", "Search file paths from snapshot metadata."),
            "search_text": ToolDefinition("search_text", "Search text content using ripgrep over a cached prefix."),
            "read_file": ToolDefinition("read_file", "Read a bounded line range from one snapshot file."),
        }
        return cls(tools=tuple(definitions[name] for name in config.enabled if name in definitions))

    def response_tools(self) -> list[dict[str, Any]]:
        schemas = {
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
                    "path_glob": {"type": ["string", "null"], "description": "Optional ripgrep path glob scoped under path_prefix."},
                    "case_sensitive": {"type": "boolean"},
                    "context_lines": {"type": "integer", "minimum": 0, "maximum": 5},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
                    "cursor": {"type": ["string", "null"], "description": "Opaque pagination cursor from a previous result."},
                },
                "required": ["query", "mode", "path_prefix", "path_glob", "case_sensitive", "context_lines", "max_results", "cursor"],
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
        }
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": schemas[tool.name],
                "strict": True,
            }
            for tool in self.tools
        ]
