from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from backend.config import ToolsConfig
from backend.execution.tool_registry import ToolCapability, ToolDefinition, ToolRegistry
from backend.security import is_secret_path

DEFAULT_TOOL_POLICY_VERSION = "analysis-tool-permissions-v2"
DEFAULT_TOOL_POLICY_HASH = "sha256:" + hashlib.sha256(DEFAULT_TOOL_POLICY_VERSION.encode()).hexdigest()


class PermissionDecision(StrEnum):
    DENY = "deny"
    ASK = "ask"
    ALLOW = "allow"


@dataclass(frozen=True)
class PermissionResult:
    decision: PermissionDecision
    reason_code: str
    message: str
    policy_hash: str = DEFAULT_TOOL_POLICY_HASH
    capability: ToolCapability | None = None
    read_only: bool | None = None
    idempotent: bool | None = None
    requires_analysis_id: bool | None = None


class PermissionEngine:
    def evaluate(
        self, *, tool_name: str, arguments: dict[str, Any], tools_config: ToolsConfig | None = None
    ) -> PermissionDecision:
        return self.evaluate_result(tool_name=tool_name, arguments=arguments, tools_config=tools_config).decision

    def evaluate_result(
        self, *, tool_name: str, arguments: dict[str, Any], tools_config: ToolsConfig | None = None
    ) -> PermissionResult:
        registry = ToolRegistry.from_config(tools_config or ToolsConfig())
        definitions = {tool.name: tool for tool in registry.tools}
        tool = definitions.get(tool_name)
        if tool is None:
            return PermissionResult(PermissionDecision.DENY, "TOOL_NOT_ENABLED", f"Tool is not enabled: {tool_name}")

        for name in ("path", "path_prefix", "glob", "path_glob"):
            path = arguments.get(name)
            if isinstance(path, str) and _is_unsafe_path(path):
                return _tool_result(tool, PermissionDecision.DENY, "UNSAFE_PATH", f"Unsafe repository path in {name}.")
            if isinstance(path, str) and is_secret_path(path):
                return _tool_result(
                    tool, PermissionDecision.DENY, "SECRET_PATH_DENIED", f"Secret path denied in {name}."
                )

        return _tool_result(tool, PermissionDecision.ALLOW, "ALLOWED", "Tool call is allowed.")


def _tool_result(
    tool: ToolDefinition, decision: PermissionDecision, reason_code: str, message: str
) -> PermissionResult:
    return PermissionResult(
        decision,
        reason_code,
        message,
        capability=tool.capability,
        read_only=tool.read_only,
        idempotent=tool.idempotent,
        requires_analysis_id=tool.requires_analysis_id,
    )


def _is_unsafe_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith(("/", "//", "~", ".git/", "../"))
        or ":" in normalized
        or normalized == ".git"
        or normalized == ".."
        or "/../" in normalized
        or normalized.endswith("/..")
    )
