from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class AgentSessionState:
    analysis_id: UUID
    agent_id: UUID
    snapshot_id: UUID | None
    config_snapshot_id: UUID
    status: str
    effective_model: str
    latest_response_id: str | None
    turn_count: int
    max_turns: int
    effective_limits_json: dict[str, Any]
    effective_runtime_json: dict[str, Any]


@dataclass(frozen=True)
class ModelToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    response_id: str
    output_text: str
    tool_calls: list[ModelToolCall]
    usage: dict[str, int]
    output_items: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class CompactionResponse:
    compaction_id: str
    output: list[dict[str, Any]]
    usage: dict[str, int]


@dataclass(frozen=True)
class CompactionDecision:
    strategy: str | None = None
    remote_output: list[dict[str, Any]] | None = None
    replacement_input: list[dict[str, Any]] | None = None

    @property
    def compacted(self) -> bool:
        return self.strategy is not None
