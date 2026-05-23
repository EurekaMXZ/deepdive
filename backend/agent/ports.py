from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from backend.agent.models import AgentSessionState, ModelResponse
from backend.events import EventEnvelope


class ResponsesRunner(Protocol):
    async def create_response(self, request: dict[str, Any]) -> ModelResponse:
        ...


class AgentRepository(Protocol):
    async def get_session(self, agent_id: UUID) -> AgentSessionState | None:
        ...

    async def start_turn(
        self,
        *,
        session: AgentSessionState,
        trigger_event_id: UUID | None = None,
        trigger_domain_key: str | None = None,
    ) -> UUID:
        ...

    async def load_context_items(self, *, session: AgentSessionState) -> list[dict[str, Any]]:
        ...

    async def load_instruction_files(self, *, session: AgentSessionState) -> list[dict[str, Any]]:
        ...

    async def load_config_snapshot(self, *, session: AgentSessionState) -> dict[str, Any] | None:
        ...

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
    ) -> None:
        ...

    async def update_session_status(self, *, agent_id: UUID, status: str) -> None:
        ...

    async def save_context_assembly(self, **kwargs) -> None:
        ...

    async def complete_turn(self, **kwargs) -> None:
        ...

    async def fail_turn(self, *, turn_id: UUID, error_code: str, error_message: str) -> None:
        ...

    async def update_latest_response(self, *, agent_id: UUID, response_id: str) -> None:
        ...

    async def create_tool_call(self, **kwargs) -> UUID:
        ...

    async def request_tool_call(
        self,
        *,
        tool_call_kwargs: dict[str, Any],
        analysis_id: UUID,
        agent_id: UUID,
        stream_event_type: str,
        stream_payload: dict[str, Any],
        event: EventEnvelope,
    ) -> UUID:
        ...

    async def find_completed_tool_call(self, *, agent_id: UUID, tool_name: str, arguments_json: dict[str, Any]) -> dict[str, Any] | None:
        ...

    async def count_tool_calls(self, *, agent_id: UUID) -> int:
        ...

    async def get_pending_tool_output(self, *, tool_call_id: UUID) -> dict[str, Any] | None:
        ...

    async def has_turn_for_event(self, *, agent_id: UUID, event_id: UUID) -> bool:
        ...

    async def get_turn_for_event(self, *, agent_id: UUID, event_id: UUID) -> dict[str, Any] | None:
        ...

    async def get_turn_for_domain_key(self, *, agent_id: UUID, trigger_domain_key: str) -> dict[str, Any] | None:
        ...

    async def get_pending_tool_call_for_turn(self, *, turn_id: UUID) -> dict[str, Any] | None:
        ...

    async def complete_analysis(self, *, analysis_id: UUID, agent_id: UUID, output_text: str) -> bool:
        ...

    async def fail_analysis(self, *, analysis_id: UUID, agent_id: UUID, error_code: str, error_message: str) -> bool:
        ...

    async def add_memory_summary(self, **kwargs) -> None:
        ...

    async def add_outbox(self, event: EventEnvelope) -> None:
        ...
