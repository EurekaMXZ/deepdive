from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Any

from backend.config import ToolsConfig
from backend.security import is_secret_path


DEFAULT_TOOL_POLICY_VERSION = "readonly-source-tool-permissions-v1"
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


class PermissionEngine:
    def evaluate(self, *, tool_name: str, arguments: dict[str, Any], tools_config: ToolsConfig | None = None) -> PermissionDecision:
        return self.evaluate_result(tool_name=tool_name, arguments=arguments, tools_config=tools_config).decision

    def evaluate_result(self, *, tool_name: str, arguments: dict[str, Any], tools_config: ToolsConfig | None = None) -> PermissionResult:
        from backend.execution.tool_registry import ToolRegistry

        registry = ToolRegistry.from_config(tools_config or ToolsConfig())
        if tool_name not in {tool.name for tool in registry.tools}:
            return PermissionResult(PermissionDecision.DENY, "TOOL_NOT_ENABLED", f"Tool is not enabled: {tool_name}")

        for name in ("path", "path_prefix", "glob", "path_glob"):
            path = arguments.get(name)
            if isinstance(path, str) and _is_unsafe_path(path):
                return PermissionResult(PermissionDecision.DENY, "UNSAFE_PATH", f"Unsafe repository path in {name}.")
            if isinstance(path, str) and is_secret_path(path):
                return PermissionResult(PermissionDecision.DENY, "SECRET_PATH_DENIED", f"Secret path denied in {name}.")

        return PermissionResult(PermissionDecision.ALLOW, "ALLOWED", "Tool call is allowed.")


def _is_unsafe_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith("/")
        or normalized.startswith("//")
        or normalized.startswith("~")
        or ":" in normalized
        or normalized.startswith(".git/")
        or normalized == ".git"
        or normalized == ".."
        or normalized.startswith("../")
        or "/../" in normalized
        or normalized.endswith("/..")
    )
