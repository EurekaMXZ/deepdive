from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from backend.agent.models import AgentSessionState
from backend.db.connections import ConnectionSource, connection_from
from backend.security import is_secret_path, visible_path_sql


class AgentContextStore:
    def __init__(self, connection_or_database: ConnectionSource) -> None:
        self._connection_or_database = connection_or_database

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def load_context_items(self, *, session: AgentSessionState) -> list[dict[str, Any]]:
        repository_metadata = await self.load_repository_metadata(session=session)
        tree = await self._load_tree(session.snapshot_id) if session.snapshot_id else []
        memory = await self.load_latest_memory_summary(agent_id=session.agent_id)
        todo = await self.load_latest_todo_list(agent_id=session.agent_id)
        items: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "请分析这个仓库的源码结构。先使用 list_files/search_file/search_text/read_file 获取源码证据; "
                            "当源码、依赖文件、配置、lockfile、Docker/CI 或测试中出现外部依赖、框架、SDK、API、协议、"
                            "运行时、数据库、中间件、部署平台、认证机制、加密算法或第三方服务时, 使用 web_search 查阅"
                            "相关资料, 优先核对官方文档或权威来源。不要在没有仓库线索时开局泛搜; 搜索结果可能过时, "
                            "只能作为背景信息, 不能替代源码、依赖文件、配置和测试证据。若文档工具可用, 必须将最终材料沉淀为多级 Markdown document artifacts, "
                            "严格按 profile 的规则创建由证据驱动的多级文档树。不要把每个项目都强行分成 Backend/Frontend; "
                            "只有仓库确实包含实质后端或前端代码时才创建这些目录。对于 CLI、机器人、库、worker-only 服务、"
                            "基础设施仓库、monorepo、移动应用或单二进制应用, 应按真实的运行时、领域、存储、API、集成、"
                            "部署和运维边界组织文档。每篇非平凡文档都要先用浅显语言解释它是什么、为什么存在、读者应该如何理解, "
                            "再给源码证据、必要源码片段、LaTeX 说明和 Mermaid 图。不要只写 `path:line-line` 作为关键证据; "
                            "关键源码引用必须先说明文件和行号, 再把最小必要代码贴入带语言标识的 fenced code block。"
                            "Markdown 必须标准、可移植: 块级数学公式使用独立行的 $$, 行内公式使用 $...$, 不要使用 \\(...\\) 或 \\[...\\]; "
                            "Mermaid 图必须能被标准渲染器解析, 节点 ID 使用简单英文标识, 含 /、:、括号、尖括号、竖线、花括号、文件路径等字符的标签必须加引号。"
                            "文档使用外部资料时, 必须用 Markdown 引用块并以“引用”引出, 或用定义列表引出相关概念, "
                            "随后立刻说明它对应本仓库的哪些文件、依赖版本、配置项或测试。"
                            "完成后用 document_finalize 标记已完成文档。"
                        ),
                    }
                ],
            }
        ]
        if repository_metadata:
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": _repository_metadata_context_text(repository_metadata),
                        }
                    ],
                }
            )
        if tree:
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "当前 snapshot 的文件树摘要:\n" + "\n".join(tree[:500]),
                        }
                    ],
                }
            )
        if memory is not None:
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "已 compact 的上下文摘要:\n" + json.dumps(memory, ensure_ascii=False),
                        }
                    ],
                }
            )
        if todo is not None:
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": _todo_context_text(todo),
                        }
                    ],
                }
            )
        return items

    async def load_repository_metadata(self, *, session: AgentSessionState) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT
                        a.repository_url,
                        a.requested_ref,
                        snap.resolved_commit_sha,
                        snap.tree_sha,
                        snap.file_count,
                        snap.total_bytes
                    FROM analyses a
                    LEFT JOIN snapshots snap ON snap.id = :snapshot_id
                    WHERE a.id = :analysis_id
                    LIMIT 1
                    """
                ),
                {"analysis_id": session.analysis_id, "snapshot_id": session.snapshot_id},
            )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def load_instruction_files(self, *, session: AgentSessionState) -> list[dict[str, Any]]:
        if session.snapshot_id is None:
            return []
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT path, scope_path, depth, content_hash, content_ref
                    FROM agent_instruction_files
                    WHERE snapshot_id = :snapshot_id
                    ORDER BY depth, path
                    """
                ),
                {"snapshot_id": session.snapshot_id},
            )
        return [dict(row) for row in result.mappings().all()]

    async def load_config_snapshot(self, *, session: AgentSessionState) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT config_json
                    FROM config_snapshots
                    WHERE id = :config_snapshot_id
                    """
                ),
                {"config_snapshot_id": session.config_snapshot_id},
            )
        row = result.mappings().first()
        return row["config_json"] if row is not None else None

    async def _load_tree(self, snapshot_id: UUID) -> list[str]:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    f"""
                    SELECT path
                    FROM snapshot_files
                    WHERE snapshot_id = :snapshot_id
                      AND {visible_path_sql()}
                    ORDER BY path
                    LIMIT 500
                    """
                ),
                {"snapshot_id": snapshot_id},
            )
        return [row["path"] for row in result.mappings().all() if not is_secret_path(str(row["path"]))]

    async def load_latest_memory_summary(self, *, agent_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT summary_json
                    FROM memory_summaries
                    WHERE agent_id = :agent_id
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"agent_id": agent_id},
            )
        row = result.mappings().first()
        return row["summary_json"] if row is not None else None

    async def load_latest_todo_list(self, *, agent_id: UUID) -> dict[str, Any] | None:
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT version, items_json, note
                    FROM agent_todo_lists
                    WHERE agent_id = :agent_id
                    ORDER BY version DESC
                    LIMIT 1
                    """
                ),
                {"agent_id": agent_id},
            )
        row = result.mappings().first()
        if row is None:
            return None
        return {
            "version": int(row["version"]),
            "items": _todo_items_from_json(row["items_json"]),
            "note": row.get("note"),
        }


def _todo_items_from_json(value: Any) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for item in cast(list[Any], value) if isinstance(value, list) else []:
        if isinstance(item, dict):
            raw_item = cast(dict[Any, Any], item)
            items.append({str(key): raw_item[key] for key in raw_item})
    return items


def _todo_context_text(todo: dict[str, Any]) -> str:
    lines = [
        "当前 TODO 计划:",
        f"version: {int(todo['version'])}",
    ]
    for item in todo.get("items", []):
        if isinstance(item, dict):
            item = cast(dict[str, object], item)
            lines.append(f"- [{item.get('status')}] {item.get('id')} - {item.get('title')}")
    if todo.get("note"):
        lines.append(f"note: {todo['note']}")
    return "\n".join(lines)


def _repository_metadata_context_text(metadata: dict[str, Any]) -> str:
    lines = ["当前分析仓库元数据:"]
    for key in ("repository_url", "requested_ref", "resolved_commit_sha", "tree_sha", "file_count", "total_bytes"):
        value = metadata.get(key)
        if value is not None:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)
