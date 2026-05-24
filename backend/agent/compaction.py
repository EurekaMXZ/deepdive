from __future__ import annotations

import json
from typing import Any

from backend.agent.models import AgentSessionState
from backend.agent.ports import ContextAssemblyRepository
from backend.config import app_config_from_json


class ContextCompactor:
    def __init__(self, *, repository: ContextAssemblyRepository) -> None:
        self._repository = repository

    async def build_summary(self, *, session: AgentSessionState, context_items: list[dict[str, Any]]) -> dict[str, Any]:
        goal = await self._goal(session=session)
        focus_paths = _focus_paths_from_context_items(context_items)
        next_action = _next_action(goal=goal, focus_paths=focus_paths)
        return {
            "goal": goal,
            "completed_steps": _completed_steps_from_context_items(context_items) or ["已组装当前轮上下文。"],
            "confirmed_facts": _confirmed_facts_from_context_items(context_items),
            "active_hypotheses": [],
            "open_questions": [],
            "focus_paths": focus_paths,
            "next_action": next_action,
        }

    async def _goal(self, *, session: AgentSessionState) -> str:
        config = app_config_from_json(await self._repository.load_config_snapshot(session=session))
        profile = config.analysis.profiles[config.analysis.default_profile]
        return profile.goal or f"继续执行分析 profile：{config.analysis.default_profile}。"


def _next_action(*, goal: str, focus_paths: list[str]) -> str:
    if focus_paths:
        return f"继续围绕 {', '.join(focus_paths[:5])} 推进当前任务：{goal}"
    return f"继续推进当前任务：{goal}"


def _completed_steps_from_context_items(context_items: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    for item in context_items[-12:]:
        payload = item.get("payload_json")
        if not isinstance(payload, dict):
            continue
        item_type = str(item.get("item_type") or payload.get("type") or "")
        if item_type == "function_call":
            name = str(payload.get("name") or "tool")
            arguments = str(payload.get("arguments") or "")
            steps.append(f"已请求工具 {name} {arguments[:240]}")
        elif item_type == "function_call_output":
            call_id = str(payload.get("call_id") or "")
            steps.append(f"已收到工具结果 {call_id}".strip())
        elif item_type == "assistant_output":
            text = _context_payload_text(payload)
            if text:
                steps.append("已生成回答片段：" + text[:240])
    return steps[:20]


def _confirmed_facts_from_context_items(context_items: list[dict[str, Any]]) -> list[str]:
    facts: list[str] = []
    for item in context_items[-12:]:
        payload = item.get("payload_json")
        if not isinstance(payload, dict):
            continue
        item_type = str(item.get("item_type") or payload.get("type") or "")
        if item_type == "function_call_output":
            text = str(payload.get("output") or "")
            for path in _repo_paths_from_text(text):
                facts.append(f"工具结果涉及路径 {path}")
        elif item_type == "assistant_output":
            text = _context_payload_text(payload)
            if text:
                facts.append(text[:240])
    return _dedupe_preserve_order(facts)[:20]


def _focus_paths_from_context_items(context_items: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in context_items:
        payload = item.get("payload_json")
        if isinstance(payload, dict):
            paths.extend(_repo_paths_from_text(json.dumps(payload, ensure_ascii=False)))
    return _dedupe_preserve_order(paths)[:50]


def _context_payload_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("text"), str):
        return str(payload["text"])
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text") for part in content if isinstance(part, dict) and isinstance(part.get("text"), str)]
        return "\n".join(str(part) for part in parts)
    return ""


def _repo_paths_from_text(value: str) -> list[str]:
    paths: list[str] = []
    for raw in value.replace("\\n", " ").replace("\n", " ").replace(",", " ").split():
        token = raw.strip("`'\"[]{}()<>;:")
        if not token or "/" not in token or token.startswith(("http://", "https://")):
            continue
        token = token.replace("\\", "/").strip("/")
        parts = [part for part in token.split("/") if part and part != "."]
        if not parts or any(part == ".." for part in parts):
            continue
        paths.append("/".join(parts))
    return paths


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
