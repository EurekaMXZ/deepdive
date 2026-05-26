from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast, runtime_checkable
from uuid import UUID

from backend.config import app_config_from_json
from backend.events import EventEnvelope, EventType
from backend.execution import SourceToolExecutor, ToolExecutionContext, is_parallel_safe_tool

DENIED_TOOL_ERROR_CODES = frozenset(
    {
        "TOOL_DENIED",
        "TOOL_NOT_ENABLED",
        "UNSAFE_PATH",
        "SECRET_PATH_DENIED",
        "ASK_UNSUPPORTED",
    }
)


class ExecutionToolCallRepository(Protocol):
    async def claim_queued_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None: ...

    async def get_analysis_status(self, analysis_id: UUID) -> str | None: ...

    async def mark_completed(
        self,
        *,
        tool_call_id: UUID,
        result: dict[str, Any],
        result_ref: str | None = None,
        duration_ms: int,
        permission_decision: str = "allow",
    ) -> None: ...

    async def mark_failed(
        self,
        *,
        tool_call_id: UUID,
        status: str,
        error_code: str,
        error_message: str,
        duration_ms: int,
        result: dict[str, Any] | None = None,
        result_ref: str | None = None,
        permission_decision: str | None = None,
    ) -> None: ...

    async def add_stream_event(
        self, *, analysis_id: UUID, agent_id: UUID, event_type: str, payload: dict[str, Any]
    ) -> None: ...

    async def add_outbox(self, event: EventEnvelope) -> None: ...

    async def renew_tool_call_claim(self, *, tool_call_id: UUID, claim_owner: str) -> bool: ...

    async def release_tool_call_claim(self, *, tool_call_id: UUID, claim_owner: str) -> bool: ...

    async def get_tool_call(self, tool_call_id: UUID) -> dict[str, Any] | None: ...


@runtime_checkable
class SupportsFinalizeToolCall(Protocol):
    async def finalize_tool_call(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        tool_call_id: UUID,
        status: str,
        result: dict[str, Any],
        result_ref: str | None,
        duration_ms: int,
        permission_decision: str,
        error_code: str | None,
        error_message: str | None,
        claim_owner: str | None,
        event: EventEnvelope,
    ) -> bool: ...


RenewClaim = Callable[..., Awaitable[bool]]


class ToolCallRuntime:
    def __init__(self) -> None:
        self._locks: dict[UUID, AsyncReadWriteLock] = {}
        self._locks_guard = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, *, agent_id: UUID, parallel_safe: bool) -> AsyncGenerator[None]:
        lock = await self._lock(agent_id)
        if parallel_safe:
            async with lock.read_lock():
                yield
            return
        async with lock.write_lock():
            yield

    async def _lock(self, agent_id: UUID) -> AsyncReadWriteLock:
        async with self._locks_guard:
            lock = self._locks.get(agent_id)
            if lock is None:
                lock = AsyncReadWriteLock()
                self._locks[agent_id] = lock
            return lock


class AsyncReadWriteLock:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer = False

    @asynccontextmanager
    async def read_lock(self) -> AsyncGenerator[None]:
        async with self._condition:
            await self._condition.wait_for(lambda: not self._writer)
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def write_lock(self) -> AsyncGenerator[None]:
        async with self._condition:
            await self._condition.wait_for(lambda: not self._writer and self._readers == 0)
            self._writer = True
        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()


class ExecutionCommandHandler:
    def __init__(
        self,
        *,
        tool_calls: ExecutionToolCallRepository,
        executor: SourceToolExecutor,
        heartbeat_interval_seconds: float = 60.0,
    ) -> None:
        self._tool_calls = tool_calls
        self._executor = executor
        self._heartbeat_interval_seconds = max(0.0, float(heartbeat_interval_seconds))
        self._tool_runtime = ToolCallRuntime()

    async def __call__(self, event: EventEnvelope) -> None:
        if event.event_type != EventType.TOOL_CALL_REQUESTED:
            raise ValueError(f"Unsupported execution command event: {event.event_type}")
        if event.analysis_id is None or event.agent_id is None or event.snapshot_id is None:
            raise ValueError("ToolCallRequested requires analysis_id, agent_id, snapshot_id")
        tool_call_id = UUID(str(event.payload["tool_call_id"]))
        row = await self._tool_calls.claim_queued_tool_call(tool_call_id)
        if row is None:
            republished = await self._republish_terminal_tool_call(event=event, tool_call_id=tool_call_id)
            if not republished:
                raise RuntimeError(f"Tool call {tool_call_id} is not terminal and cannot be claimed")
            return
        if event.agent_id != row["agent_id"] or event.snapshot_id != row["snapshot_id"]:
            raise ValueError("ToolCallRequested event does not match persisted tool call context")
        claim_owner = str(row["claim_owner"]) if row.get("claim_owner") else None
        analysis_status = await self._analysis_status(event.analysis_id)
        if analysis_status in {"cancelling", "cancelled"}:
            await self._cancel_claimed_tool_call(event=event, tool_call_id=tool_call_id, claim_owner=claim_owner)
            return
        heartbeat_task = self._start_heartbeat(tool_call_id=tool_call_id, claim_owner=claim_owner)
        started = time.perf_counter()
        try:
            async with self._tool_runtime.acquire(
                agent_id=event.agent_id,
                parallel_safe=is_parallel_safe_tool(str(row["tool_name"])),
            ):
                result = await self._executor.execute(
                    ToolExecutionContext(
                        tool_call_id=tool_call_id,
                        analysis_id=event.analysis_id,
                        agent_id=row["agent_id"],
                        snapshot_id=row["snapshot_id"],
                        turn_id=row.get("turn_id"),
                    ),
                    row["tool_name"],
                    dict(row["arguments_json"]),
                    config=app_config_from_json(row.get("config_json")),
                )
                result = _tool_result_with_id(result, tool_call_id=tool_call_id)
        except Exception:
            await self._release_claim(tool_call_id=tool_call_id, claim_owner=claim_owner)
            raise
        finally:
            await self._stop_heartbeat(heartbeat_task)
        duration_ms = int((time.perf_counter() - started) * 1000)
        status, event_type, error = _classify_tool_result(result)
        payload: dict[str, Any] = {"tool_call_id": str(tool_call_id)}
        if error is not None:
            payload["error"] = error
        outbox_event = EventEnvelope.new(
            event_type=event_type,
            analysis_id=event.analysis_id,
            agent_id=event.agent_id,
            snapshot_id=event.snapshot_id,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload=payload,
        )
        try:
            await self._persist_tool_result(
                analysis_id=event.analysis_id,
                agent_id=event.agent_id,
                tool_call_id=tool_call_id,
                status=status,
                result=result,
                result_ref=result.get("result_ref"),
                duration_ms=duration_ms,
                permission_decision="deny" if status == "denied" else "allow",
                error_code=error["code"] if error is not None else None,
                error_message=error["message"] if error is not None else None,
                claim_owner=claim_owner,
                event=outbox_event,
            )
        except Exception:
            await self._release_claim(tool_call_id=tool_call_id, claim_owner=claim_owner)
            raise

    async def _analysis_status(self, analysis_id: UUID) -> str | None:
        status = await self._tool_calls.get_analysis_status(analysis_id)
        return str(status) if status is not None else None

    async def _cancel_claimed_tool_call(
        self, *, event: EventEnvelope, tool_call_id: UUID, claim_owner: str | None
    ) -> None:
        if event.analysis_id is None or event.agent_id is None:
            raise ValueError("Tool call cancellation requires analysis_id and agent_id")
        result: dict[str, Any] = {
            "ok": False,
            "tool_name": "cancelled",
            "error": {
                "code": "TOOL_CALL_CANCELLED",
                "message": "Analysis was cancelled before this tool call executed.",
                "retryable": False,
            },
        }
        result = _tool_result_with_id(result, tool_call_id=tool_call_id)
        error = _error_payload(result)
        outbox_event = EventEnvelope.new(
            event_type=EventType.TOOL_CALL_FAILED,
            analysis_id=event.analysis_id,
            agent_id=event.agent_id,
            snapshot_id=event.snapshot_id,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload={
                "tool_call_id": str(tool_call_id),
                "error": error,
            },
        )
        try:
            await self._persist_tool_result(
                analysis_id=event.analysis_id,
                agent_id=event.agent_id,
                tool_call_id=tool_call_id,
                status="cancelled",
                result=result,
                result_ref=None,
                duration_ms=0,
                permission_decision="deny",
                error_code=error["code"],
                error_message=error["message"],
                claim_owner=claim_owner,
                event=outbox_event,
            )
        except Exception:
            await self._release_claim(tool_call_id=tool_call_id, claim_owner=claim_owner)
            raise

    async def _persist_tool_result(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        tool_call_id: UUID,
        status: str,
        result: dict[str, Any],
        result_ref: str | None,
        duration_ms: int,
        permission_decision: str,
        error_code: str | None,
        error_message: str | None,
        claim_owner: str | None,
        event: EventEnvelope,
    ) -> None:
        if isinstance(self._tool_calls, SupportsFinalizeToolCall):
            await self._tool_calls.finalize_tool_call(
                analysis_id=analysis_id,
                agent_id=agent_id,
                tool_call_id=tool_call_id,
                status=status,
                result=result,
                result_ref=result_ref,
                duration_ms=duration_ms,
                permission_decision=permission_decision,
                error_code=error_code,
                error_message=error_message,
                claim_owner=claim_owner,
                event=event,
            )
            return

        if status == "completed":
            await self._tool_calls.mark_completed(
                tool_call_id=tool_call_id,
                result=result,
                result_ref=result_ref,
                duration_ms=duration_ms,
                permission_decision=permission_decision,
            )
        else:
            if error_code is None or error_message is None:
                raise RuntimeError("Non-completed tool result did not include an error payload")
            await self._tool_calls.mark_failed(
                tool_call_id=tool_call_id,
                status=status,
                error_code=error_code,
                error_message=error_message,
                duration_ms=duration_ms,
                result=result,
                result_ref=result_ref,
                permission_decision=permission_decision,
            )
        await self._tool_calls.add_stream_event(
            analysis_id=analysis_id,
            agent_id=agent_id,
            event_type="tool_result",
            payload=result,
        )
        await self._tool_calls.add_outbox(event)

    def _start_heartbeat(self, *, tool_call_id: UUID, claim_owner: str | None) -> asyncio.Task[None] | None:
        if not claim_owner:
            return None
        return asyncio.create_task(
            self._heartbeat_claim(
                tool_call_id=tool_call_id,
                claim_owner=str(claim_owner),
                renew=self._tool_calls.renew_tool_call_claim,
            )
        )

    async def _stop_heartbeat(self, task: asyncio.Task[None] | None) -> None:
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    async def _heartbeat_claim(self, *, tool_call_id: UUID, claim_owner: str, renew: RenewClaim) -> None:
        while True:
            if self._heartbeat_interval_seconds > 0:
                await asyncio.sleep(self._heartbeat_interval_seconds)
            renewed = await renew(tool_call_id=tool_call_id, claim_owner=claim_owner)
            if not renewed:
                return
            if self._heartbeat_interval_seconds <= 0:
                return

    async def _release_claim(self, *, tool_call_id: UUID, claim_owner: str | None) -> None:
        if not claim_owner:
            return
        await self._tool_calls.release_tool_call_claim(tool_call_id=tool_call_id, claim_owner=str(claim_owner))

    async def _republish_terminal_tool_call(self, *, event: EventEnvelope, tool_call_id: UUID) -> bool:
        row = await self._tool_calls.get_tool_call(tool_call_id)
        if not isinstance(row, Mapping):
            return False
        status = row.get("status")
        if status not in {"completed", "failed", "denied", "cancelled"}:
            return False
        if event.agent_id != row.get("agent_id") or event.snapshot_id != row.get("snapshot_id"):
            raise ValueError("ToolCallRequested event does not match persisted terminal tool call context")
        event_type = {
            "completed": EventType.TOOL_CALL_COMPLETED,
            "failed": EventType.TOOL_CALL_FAILED,
            "denied": EventType.TOOL_CALL_DENIED,
            "cancelled": EventType.TOOL_CALL_FAILED,
        }[status]
        payload: dict[str, Any] = {"tool_call_id": str(tool_call_id)}
        if status in {"failed", "denied", "cancelled"}:
            payload["error"] = {
                "code": str(
                    row.get("error_code") or ("TOOL_CALL_CANCELLED" if status == "cancelled" else str(status).upper())
                ),
                "message": row.get("error_message") or f"Tool call {status}",
            }
        await self._tool_calls.add_outbox(
            EventEnvelope.new(
                event_type=event_type,
                analysis_id=event.analysis_id,
                agent_id=event.agent_id,
                snapshot_id=event.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload=payload,
            )
        )
        return True


def _classify_tool_result(result: dict[str, Any]) -> tuple[str, EventType, dict[str, Any] | None]:
    if result.get("ok") is True:
        return "completed", EventType.TOOL_CALL_COMPLETED, None

    error = _error_payload(result)
    code = error["code"]
    message = error["message"]
    retryable = bool(error["retryable"])
    event_error: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    if code in DENIED_TOOL_ERROR_CODES:
        return "denied", EventType.TOOL_CALL_DENIED, event_error
    return "failed", EventType.TOOL_CALL_FAILED, event_error


def _error_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    raw_error = result.get("error")
    error: Mapping[str, Any] = cast(Mapping[str, Any], raw_error) if isinstance(raw_error, Mapping) else {}
    return {
        "code": str(error.get("code") or "TOOL_FAILED"),
        "message": str(error.get("message") or "Tool call failed"),
        "retryable": bool(error.get("retryable", False)),
    }


def _tool_result_with_id(result: dict[str, Any], *, tool_call_id: UUID) -> dict[str, Any]:
    payload = dict(result)
    payload["tool_call_id"] = str(tool_call_id)
    return payload
