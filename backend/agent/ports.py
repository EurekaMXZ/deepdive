from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from backend.agent.models import AgentSessionState, CompactionResponse, ModelResponse
from backend.events import EventEnvelope


class ResponsesRunner(Protocol):
    async def create_response(self, request: dict[str, Any]) -> ModelResponse: ...

    async def compact_response(self, request: dict[str, Any]) -> CompactionResponse: ...


class ContextAssemblyRepository(Protocol):
    async def load_context_items(self, *, session: AgentSessionState) -> list[dict[str, Any]]: ...

    async def load_uncompacted_context_items(self, *, agent_id: UUID, limit: int = 12) -> list[dict[str, Any]]: ...

    async def load_latest_memory_summary(self, *, agent_id: UUID) -> dict[str, Any] | None: ...

    async def load_instruction_files(self, *, session: AgentSessionState) -> list[dict[str, Any]]: ...

    async def load_config_snapshot(self, *, session: AgentSessionState) -> dict[str, Any] | None: ...

    async def save_context_assembly(self, **kwargs: Any) -> None: ...


class AgentContextItemRepository(Protocol):
    async def append_context_item(
        self,
        *,
        agent_id: UUID,
        turn_id: UUID | None,
        item_type: str,
        payload: dict[str, Any],
        response_id: str | None = None,
        source: str,
        idempotency_key: str | None = None,
    ) -> None: ...

    async def compact_context_items(
        self,
        *,
        agent_id: UUID,
        compacted_until_seq: int,
        compacted_until_turn: int,
        summary_json: dict[str, Any],
        evidence_ids_json: list[Any],
        focus_paths_json: list[str],
        next_action: str | None,
    ) -> None: ...

    async def add_memory_summary(
        self,
        *,
        agent_id: UUID,
        compacted_until_turn: int,
        summary_json: dict[str, Any],
        evidence_ids_json: list[Any],
        focus_paths_json: list[str],
        next_action: str | None,
    ) -> None: ...

    async def save_compacted_context_window(
        self,
        *,
        agent_id: UUID,
        turn_id: UUID,
        compacted_until_turn: int,
        compaction_id: str,
        output_json: list[dict[str, Any]],
        usage_json: dict[str, int],
        strategy: str = "remote",
    ) -> None: ...


class AgentStreamRepository(Protocol):
    async def add_stream_event(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        turn_id: UUID | None = None,
        attempt: int | None = None,
        response_id: str | None = None,
        state: str | None = None,
    ) -> None: ...


class AgentTurnRepository(Protocol):
    async def get_session(self, agent_id: UUID) -> AgentSessionState | None: ...

    async def start_turn(
        self,
        *,
        session: AgentSessionState,
        trigger_event_id: UUID | None = None,
        trigger_domain_key: str | None = None,
    ) -> UUID: ...

    async def update_session_status(self, *, agent_id: UUID, status: str) -> None: ...

    async def complete_turn(
        self,
        *,
        turn_id: UUID,
        response_id: str | None = None,
        previous_response_id: str | None = None,
        input_ref: str | None = None,
        output_ref: str | None = None,
        output_text: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None: ...

    async def fail_turn(self, *, turn_id: UUID, error_code: str, error_message: str) -> None: ...

    async def update_latest_response(self, *, agent_id: UUID, response_id: str) -> None: ...


class AgentToolCallRepository(Protocol):
    async def create_tool_call(self, **kwargs: Any) -> UUID: ...

    async def request_tool_call(
        self,
        *,
        tool_call_kwargs: dict[str, Any],
        analysis_id: UUID,
        agent_id: UUID,
        stream_event_type: str,
        stream_payload: dict[str, Any],
        event: EventEnvelope,
    ) -> UUID: ...

    async def complete_turn_with_tool_calls(
        self,
        *,
        turn_id: UUID,
        response_id: str,
        previous_response_id: str | None,
        input_ref: str,
        output_ref: str,
        usage: dict[str, int],
        latest_response_agent_id: UUID,
        tool_call_requests: list[dict[str, Any]],
        analysis_id: UUID,
        agent_id: UUID,
        output_items: list[dict[str, Any]] | None = None,
    ) -> list[UUID]: ...

    async def find_completed_tool_call(
        self, *, agent_id: UUID, tool_name: str, arguments_json: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def count_tool_calls(self, *, agent_id: UUID) -> int: ...

    async def get_pending_tool_output(self, *, tool_call_id: UUID) -> dict[str, Any] | None: ...

    async def load_ready_tool_outputs_for_turn(self, *, turn_id: UUID) -> list[dict[str, Any]] | None: ...

    async def has_turn_for_event(self, *, agent_id: UUID, event_id: UUID) -> bool: ...

    async def get_turn_for_event(self, *, agent_id: UUID, event_id: UUID) -> dict[str, Any] | None: ...

    async def get_turn_for_domain_key(self, *, agent_id: UUID, trigger_domain_key: str) -> dict[str, Any] | None: ...

    async def get_pending_tool_call_for_turn(self, *, turn_id: UUID) -> dict[str, Any] | None: ...


class AgentAnalysisRepository(Protocol):
    async def complete_analysis(self, *, analysis_id: UUID, agent_id: UUID, output_text: str) -> bool: ...

    async def fail_analysis(
        self, *, analysis_id: UUID, agent_id: UUID, error_code: str, error_message: str
    ) -> bool: ...


class AgentOutboxRepository(Protocol):
    async def add_outbox(self, event: EventEnvelope) -> None: ...


class AgentRepository(
    ContextAssemblyRepository,
    AgentContextItemRepository,
    AgentStreamRepository,
    AgentTurnRepository,
    AgentToolCallRepository,
    AgentAnalysisRepository,
    AgentOutboxRepository,
    Protocol,
):
    """Composite port kept for the command handler while focused ports serve smaller collaborators."""

    ...
