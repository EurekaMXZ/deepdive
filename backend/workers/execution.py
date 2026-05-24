from __future__ import annotations

import asyncio
import time
from uuid import UUID

from backend.events import EventEnvelope, EventType
from backend.execution import SourceToolExecutor, ToolExecutionContext
from backend.execution.repository import PostgresToolCallRepository
from backend.config import app_config_from_json


DENIED_TOOL_ERROR_CODES = frozenset(
    {
        "TOOL_DENIED",
        "TOOL_NOT_ENABLED",
        "UNSAFE_PATH",
        "SECRET_PATH_DENIED",
        "ASK_UNSUPPORTED",
    }
)


class ExecutionCommandHandler:
    def __init__(
        self,
        *,
        tool_calls: PostgresToolCallRepository,
        executor: SourceToolExecutor,
        heartbeat_interval_seconds: float = 60.0,
    ) -> None:
        self._tool_calls = tool_calls
        self._executor = executor
        self._heartbeat_interval_seconds = max(0.0, float(heartbeat_interval_seconds))

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
        claim_owner = row.get("claim_owner")
        analysis_status = await self._analysis_status(event.analysis_id)
        if analysis_status in {"cancelling", "cancelled"}:
            await self._cancel_claimed_tool_call(event=event, tool_call_id=tool_call_id, claim_owner=claim_owner)
            return
        heartbeat_task = self._start_heartbeat(tool_call_id=tool_call_id, claim_owner=claim_owner)
        started = time.perf_counter()
        try:
            result = await self._executor.execute(
                ToolExecutionContext(
                    tool_call_id=tool_call_id,
                    analysis_id=event.analysis_id,
                    agent_id=row["agent_id"],
                    snapshot_id=row["snapshot_id"],
                ),
                row["tool_name"],
                dict(row["arguments_json"]),
                config=app_config_from_json(row.get("config_json")),
            )
        except Exception:
            await self._release_claim(tool_call_id=tool_call_id, claim_owner=claim_owner)
            raise
        finally:
            await self._stop_heartbeat(heartbeat_task)
        duration_ms = int((time.perf_counter() - started) * 1000)
        status, event_type, error = _classify_tool_result(result)
        payload = {"tool_call_id": str(tool_call_id)}
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
        finalize_tool_call = getattr(self._tool_calls, "finalize_tool_call", None)
        if finalize_tool_call is not None:
            try:
                await finalize_tool_call(
                    analysis_id=event.analysis_id,
                    agent_id=event.agent_id,
                    tool_call_id=tool_call_id,
                    status=status,
                    result=result,
                    result_ref=result.get("result_ref") if isinstance(result, dict) else None,
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
            return
        if status == "completed":
            await self._tool_calls.mark_completed(
                tool_call_id=tool_call_id,
                result=result,
                result_ref=result.get("result_ref") if isinstance(result, dict) else None,
                duration_ms=duration_ms,
                permission_decision="allow",
            )
        else:
            await self._tool_calls.mark_failed(
                tool_call_id=tool_call_id,
                status=status,
                error_code=error["code"],
                error_message=error["message"],
                duration_ms=duration_ms,
                result=result,
                result_ref=result.get("result_ref") if isinstance(result, dict) else None,
                permission_decision="deny" if status == "denied" else "allow",
            )
        await self._tool_calls.add_stream_event(
            analysis_id=event.analysis_id,
            agent_id=event.agent_id,
            event_type="tool_result",
            payload=result,
        )
        await self._tool_calls.add_outbox(
            outbox_event
        )

    async def _analysis_status(self, analysis_id) -> str | None:
        get_analysis_status = getattr(self._tool_calls, "get_analysis_status", None)
        if get_analysis_status is None:
            return None
        status = await get_analysis_status(analysis_id)
        return str(status) if status is not None else None

    async def _cancel_claimed_tool_call(self, *, event: EventEnvelope, tool_call_id: UUID, claim_owner: str | None) -> None:
        result = {
            "ok": False,
            "tool_name": "cancelled",
            "error": {
                "code": "TOOL_CALL_CANCELLED",
                "message": "Analysis was cancelled before this tool call executed.",
                "retryable": False,
            },
        }
        error = result["error"]
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
        finalize_tool_call = getattr(self._tool_calls, "finalize_tool_call", None)
        if finalize_tool_call is not None:
            await finalize_tool_call(
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
            return
        await self._tool_calls.mark_failed(
            tool_call_id=tool_call_id,
            status="cancelled",
            error_code=error["code"],
            error_message=error["message"],
            duration_ms=0,
            result=result,
            result_ref=None,
            permission_decision="deny",
        )
        await self._tool_calls.add_stream_event(
            analysis_id=event.analysis_id,
            agent_id=event.agent_id,
            event_type="tool_result",
            payload=result,
        )
        await self._tool_calls.add_outbox(outbox_event)

    def _start_heartbeat(self, *, tool_call_id: UUID, claim_owner: str | None):
        renew = getattr(self._tool_calls, "renew_tool_call_claim", None)
        if renew is None or not claim_owner:
            return None
        return asyncio.create_task(
            self._heartbeat_claim(
                tool_call_id=tool_call_id,
                claim_owner=str(claim_owner),
                renew=renew,
            )
        )

    async def _stop_heartbeat(self, task) -> None:
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    async def _heartbeat_claim(self, *, tool_call_id: UUID, claim_owner: str, renew) -> None:
        while True:
            if self._heartbeat_interval_seconds > 0:
                await asyncio.sleep(self._heartbeat_interval_seconds)
            renewed = await renew(tool_call_id=tool_call_id, claim_owner=claim_owner)
            if not renewed:
                return
            if self._heartbeat_interval_seconds <= 0:
                return

    async def _release_claim(self, *, tool_call_id: UUID, claim_owner: str | None) -> None:
        release = getattr(self._tool_calls, "release_tool_call_claim", None)
        if release is None or not claim_owner:
            return
        await release(tool_call_id=tool_call_id, claim_owner=str(claim_owner))

    async def _republish_terminal_tool_call(self, *, event: EventEnvelope, tool_call_id: UUID) -> bool:
        get_tool_call = getattr(self._tool_calls, "get_tool_call", None)
        if get_tool_call is None:
            return False
        row = await get_tool_call(tool_call_id)
        if row is None:
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
        payload = {"tool_call_id": str(tool_call_id)}
        if status in {"failed", "denied", "cancelled"}:
            payload["error"] = {
                "code": row.get("error_code") or ("TOOL_CALL_CANCELLED" if status == "cancelled" else status.upper()),
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


def _classify_tool_result(result: dict) -> tuple[str, EventType, dict | None]:
    if result.get("ok") is True:
        return "completed", EventType.TOOL_CALL_COMPLETED, None

    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    code = str(error.get("code") or "TOOL_FAILED")
    message = str(error.get("message") or "Tool call failed")
    retryable = bool(error.get("retryable", False))
    event_error = {"code": code, "message": message, "retryable": retryable}
    if code in DENIED_TOOL_ERROR_CODES:
        return "denied", EventType.TOOL_CALL_DENIED, event_error
    return "failed", EventType.TOOL_CALL_FAILED, event_error
