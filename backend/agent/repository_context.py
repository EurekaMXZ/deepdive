from __future__ import annotations

import json
from typing import Any
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
        tree = await self._load_tree(session.snapshot_id) if session.snapshot_id else []
        memory = await self.load_latest_memory_summary(agent_id=session.agent_id)
        items: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "请分析这个仓库的源码结构。先使用 list_files/search_file/search_text/read_file 获取证据, 再给出结论。",
                    }
                ],
            }
        ]
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
        return items

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
