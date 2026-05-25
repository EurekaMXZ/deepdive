from __future__ import annotations

import json
from typing import Any, cast

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
            "evidence_ids": _evidence_ids_from_context_items(context_items),
            "next_action": next_action,
        }

    async def _goal(self, *, session: AgentSessionState) -> str:
        config = app_config_from_json(await self._repository.load_config_snapshot(session=session))
        profile = config.analysis.profiles[config.analysis.default_profile]
        return profile.goal or f"继续执行分析 profile: {config.analysis.default_profile}."


def _next_action(*, goal: str, focus_paths: list[str]) -> str:
    if focus_paths:
        return f"继续围绕 {', '.join(focus_paths[:5])} 推进当前任务: {goal}"
    return f"继续推进当前任务: {goal}"


def _completed_steps_from_context_items(context_items: list[dict[str, Any]]) -> list[Any]:
    completed_call_ids = _completed_call_ids_from_context_items(context_items)
    steps: list[Any] = []
    for item in context_items[-12:]:
        payload = item.get("payload_json")
        if not isinstance(payload, dict):
            continue
        payload = cast(dict[str, Any], payload)
        item_type = str(item.get("item_type") or payload.get("type") or "")
        if item_type == "function_call":
            name = str(payload.get("name") or "tool")
            arguments = _json_object_from_value(payload.get("arguments")) or {}
            steps.append(
                {
                    "tool": name,
                    "call_id": str(payload.get("call_id") or ""),
                    "arguments": arguments,
                    "status": _tool_step_status(payload=payload, completed_call_ids=completed_call_ids),
                }
            )
        elif item_type == "function_call_output":
            call_id = str(payload.get("call_id") or "")
            steps.append(f"已收到工具结果 {call_id}".strip())
        elif item_type == "assistant_output":
            text = _context_payload_text(payload)
            if text:
                steps.append("已生成回答片段: " + text[:240])
    return steps[:20]


def _confirmed_facts_from_context_items(context_items: list[dict[str, Any]]) -> list[Any]:
    facts: list[Any] = []
    for item in context_items[-12:]:
        payload = item.get("payload_json")
        if not isinstance(payload, dict):
            continue
        payload = cast(dict[str, Any], payload)
        item_type = str(item.get("item_type") or payload.get("type") or "")
        if item_type == "function_call_output":
            output = _json_object_from_value(payload.get("output"))
            if output is None:
                continue
            evidence_ids = _evidence_ids_from_payload(output)
            result = _json_object(output.get("result"))
            if result is None:
                continue
            path = _normalize_repo_path(result.get("path"))
            if path:
                facts.append(
                    {
                        "claim": _read_result_claim(path=path, result=result),
                        "evidence_ids": evidence_ids,
                    }
                )
        elif item_type == "assistant_output":
            text = _context_payload_text(payload)
            if text:
                facts.append({"claim": text[:240], "evidence_ids": []})
    return _dedupe_facts(facts)[:20]


def _focus_paths_from_context_items(context_items: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in context_items:
        payload = item.get("payload_json")
        if not isinstance(payload, dict):
            continue
        payload = cast(dict[str, Any], payload)
        paths.extend(_paths_from_payload(payload))
    return _dedupe_preserve_order(paths)[:50]


def _evidence_ids_from_context_items(context_items: list[dict[str, Any]]) -> list[str]:
    evidence_ids: list[str] = []
    for item in context_items:
        payload = item.get("payload_json")
        if not isinstance(payload, dict):
            continue
        payload = cast(dict[str, Any], payload)
        output = _json_object_from_value(payload.get("output"))
        if output is not None:
            evidence_ids.extend(_evidence_ids_from_payload(output))
        evidence_ids.extend(_evidence_ids_from_payload(payload))
    return _dedupe_preserve_order(evidence_ids)


def _context_payload_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("text"), str):
        return str(payload["text"])
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in cast(list[Any], content):
            if isinstance(part, dict):
                part_object = cast(dict[str, Any], part)
                text = part_object.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _paths_from_payload(payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    arguments = _json_object_from_value(payload.get("arguments"))
    if arguments is not None:
        path = _normalize_repo_path(arguments.get("path") or arguments.get("path_prefix"))
        if path:
            paths.append(path)
    output = _json_object_from_value(payload.get("output"))
    if output is not None:
        paths.extend(_paths_from_payload(output))
    result = _json_object(payload.get("result"))
    if result is not None:
        path = _normalize_repo_path(result.get("path"))
        if path:
            paths.append(path)
        for item in _json_list(result.get("items")):
            if isinstance(item, dict):
                item_path = _normalize_repo_path(cast(dict[str, Any], item).get("path"))
                if item_path:
                    paths.append(item_path)
    path = _normalize_repo_path(payload.get("path"))
    if path:
        paths.append(path)
    return paths


def _read_result_claim(*, path: str, result: dict[str, Any]) -> str:
    start_line = result.get("start_line")
    end_line = result.get("end_line")
    if isinstance(start_line, int) and isinstance(end_line, int):
        return f"read_file 读取了 {path}:{start_line}-{end_line}。"
    return f"工具结果涉及路径 {path}。"


def _completed_call_ids_from_context_items(context_items: list[dict[str, Any]]) -> set[str]:
    call_ids: set[str] = set()
    for item in context_items:
        payload = item.get("payload_json")
        if not isinstance(payload, dict):
            continue
        payload = cast(dict[str, Any], payload)
        item_type = str(item.get("item_type") or payload.get("type") or "")
        if item_type != "function_call_output":
            continue
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            call_ids.add(call_id)
    return call_ids


def _tool_step_status(*, payload: dict[str, Any], completed_call_ids: set[str]) -> str:
    call_id = payload.get("call_id")
    if isinstance(call_id, str) and call_id in completed_call_ids:
        return "completed"
    status = payload.get("status")
    return str(status or "requested")


def _json_object_from_value(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _json_object(parsed)
    return None


def _json_object(value: Any) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _json_list(value: Any) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def _evidence_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("evidence_ids")
    if not isinstance(raw, list):
        return []
    values = cast(list[Any], raw)
    return [str(item) for item in values if isinstance(item, str) and item]


def _normalize_repo_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip("`'\".,;:()[]{}<>").replace("\\", "/").strip("/")
    if not stripped or stripped.startswith(("http://", "https://")) or "/" not in stripped:
        return None
    parts = [part for part in stripped.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _dedupe_facts(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, dict) else str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


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
