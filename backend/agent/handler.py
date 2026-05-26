from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from backend.agent.compaction import ContextCompactor
from backend.agent.context import ContextAssembler
from backend.agent.models import AgentSessionState, CompactionDecision, ModelResponse, ModelToolCall
from backend.agent.ports import AgentRepository, ResponsesRunner
from backend.config import AppConfig
from backend.events import EventEnvelope, EventType
from backend.events.model_stream_payloads import model_reasoning_summary_stream_payloads
from backend.execution.permissions import DEFAULT_TOOL_POLICY_HASH
from backend.execution.tool_registry import DEFAULT_TOOL_REGISTRY_VERSION


class CancelledModelStreamError(RuntimeError):
    pass


class AgentCommandHandler:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        context_assembler: ContextAssembler,
        responses_runner: ResponsesRunner,
        config: AppConfig,
        model_retry_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._context_assembler = context_assembler
        self._responses_runner = responses_runner
        self._config = config
        self._model_retry_attempts = max(1, int(model_retry_attempts))
        self._compactor = ContextCompactor(repository=repository)

    async def __call__(self, event: EventEnvelope) -> None:
        if event.event_type in {
            EventType.SNAPSHOT_READY,
            EventType.AGENT_CONTINUE_REQUESTED,
            EventType.TOOL_CALL_COMPLETED,
            EventType.TOOL_CALL_FAILED,
            EventType.TOOL_CALL_DENIED,
        }:
            await self._run_turn(event)
            return
        if event.event_type == EventType.ANALYSIS_CANCEL_REQUESTED:
            if event.analysis_id and event.agent_id:
                await self._repository.add_stream_event(
                    analysis_id=event.analysis_id,
                    agent_id=event.agent_id,
                    event_type="status",
                    payload={"status": "cancelled"},
                )
            return
        raise ValueError(f"Unsupported agent event: {event.event_type}")

    async def _run_turn(self, event: EventEnvelope) -> None:
        if event.analysis_id is None or event.agent_id is None:
            raise ValueError("Agent event requires analysis_id and agent_id")
        session = await self._repository.get_session(event.agent_id)
        if session is None:
            raise ValueError("Agent session not found")
        if session.status in TERMINAL_SESSION_STATUSES:
            return
        if session.status == "waiting_tool" and not _is_terminal_tool_event(event):
            return
        trigger_domain_key = _trigger_domain_key(event)
        existing_turn = await self._turn_for_trigger(
            agent_id=session.agent_id,
            event_id=event.event_id,
            trigger_domain_key=trigger_domain_key,
        )
        if existing_turn is not None:
            if existing_turn.get("status") == "completed":
                return
            recovered = await self._recover_incomplete_turn(
                event=event, session=session, turn_id=UUID(str(existing_turn["id"]))
            )
            if recovered:
                return
            if _is_retryable_model_turn(existing_turn):
                await self._run_model_turn(
                    event=event,
                    session=session,
                    turn_id=UUID(str(existing_turn["id"])),
                )
                return
            await self._fail_unrecoverable_turn_replay(
                event=event, session=session, turn_id=UUID(str(existing_turn["id"]))
            )
            return
        if session.snapshot_id is None and event.snapshot_id is not None:
            session = AgentSessionState(
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=event.snapshot_id,
                config_snapshot_id=session.config_snapshot_id,
                status=session.status,
                effective_model=session.effective_model,
                latest_response_id=session.latest_response_id,
                turn_count=session.turn_count,
                max_turns=session.max_turns,
                effective_limits_json=session.effective_limits_json,
                effective_runtime_json=session.effective_runtime_json,
            )
        if session.snapshot_id is None:
            raise ValueError("Agent session has no snapshot")
        if session.turn_count >= session.max_turns:
            await self._fail_max_turns_exceeded(event=event, session=session)
            return
        max_tool_calls = int(session.effective_limits_json.get("max_tool_calls") or 0)
        if max_tool_calls > 0 and await self._count_tool_calls(agent_id=session.agent_id) >= max_tool_calls:
            await self._fail_max_tool_calls_exceeded(event=event, session=session, max_tool_calls=max_tool_calls)
            return
        ready_tool_outputs = None
        if _is_terminal_tool_event(event):
            ready_tool_outputs = await self._ready_tool_outputs(event)
            if ready_tool_outputs is None:
                return

        await self._repository.update_session_status(agent_id=session.agent_id, status="calling_model")
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="status",
            payload={"status": "calling_model"},
        )
        turn_id = await self._repository.start_turn(
            session=session,
            trigger_event_id=event.event_id,
            trigger_domain_key=trigger_domain_key,
        )
        await self._run_model_turn(
            event=event,
            session=session,
            turn_id=turn_id,
            ready_tool_outputs=ready_tool_outputs,
        )

    async def _run_model_turn(
        self,
        *,
        event: EventEnvelope,
        session: AgentSessionState,
        turn_id: UUID,
        ready_tool_outputs: list[dict[str, Any]] | None = None,
    ) -> None:
        use_previous_response_id = bool(
            session.effective_runtime_json.get("use_previous_response_id", self._config.openai.use_previous_response_id)
        ) and bool(session.latest_response_id)
        extra_items = await self._tool_output_items(
            event,
            use_previous_response_id=use_previous_response_id,
            ready_tool_outputs=ready_tool_outputs,
        )
        context = await self._context_assembler.assemble(
            session=session,
            turn_id=turn_id,
            extra_items=extra_items,
            include_local_history=not use_previous_response_id,
            include_base_context=not use_previous_response_id,
        )
        compaction_context = context
        if use_previous_response_id:
            compaction_context = await self._context_assembler.assemble(
                session=session,
                turn_id=turn_id,
                extra_items=extra_items,
                include_local_history=True,
                include_base_context=True,
                persist=False,
            )
        compaction = await self._compact_if_needed(event=event, session=session, turn_id=turn_id, context=compaction_context)
        if compaction.strategy in {"remote", "remote_v2", "local_model"}:
            use_previous_response_id = False
            context = await self._context_assembler.assemble(
                session=session,
                turn_id=turn_id,
                override_input_items=compaction.replacement_input or compaction.remote_output or [],
            )
        elif compaction.compacted:
            use_previous_response_id = False
            extra_items = await self._tool_output_items(
                event,
                use_previous_response_id=False,
                ready_tool_outputs=ready_tool_outputs,
            )
            context = await self._context_assembler.assemble(
                session=session,
                turn_id=turn_id,
                extra_items=extra_items,
                include_local_history=True,
            )
            if self._context_exceeds_threshold(session=session, context=context):
                await self._fail_context_too_large_after_compact(
                    event=event, session=session, turn_id=turn_id, context=context
                )
                return
        show_reasoning_summary = bool(
            session.effective_runtime_json.get(
                "show_reasoning_summary",
                self._config.openai.show_reasoning_summary,
            )
        )
        reasoning_summary_fragments: list[str] = []
        reasoning_summary_final_emitted = False

        async def on_raw_sse_event(event_name: str, payload: dict[str, Any]) -> None:
            nonlocal reasoning_summary_final_emitted
            response_id = payload.get("response_id")
            if event_name == "model_reasoning_summary.delta":
                text = payload.get("text")
                if isinstance(text, str) and text:
                    reasoning_summary_fragments.append(text)
                    if show_reasoning_summary:
                        delta_payload: dict[str, Any] = {
                            "type": "model_reasoning_summary.delta",
                            "text": text,
                        }
                        for key in ("item_id", "response_id", "summary_index"):
                            if payload.get(key) is not None:
                                delta_payload[key] = payload[key]
                        delta_response_id = delta_payload.get("response_id") or response_id
                        await self._persist_model_reasoning_summary(
                            event_name="model_reasoning_summary.delta",
                            payload=delta_payload,
                            session=session,
                            turn_id=turn_id,
                            attempt=event.attempt,
                            response_id=delta_response_id,
                        )
            if (
                event_name == "model_reasoning_summary.done"
                and show_reasoning_summary
                and not reasoning_summary_final_emitted
            ):
                text = payload.get("text")
                final_text = text if isinstance(text, str) and text else "".join(reasoning_summary_fragments)
                if final_text:
                    summary_payload: dict[str, Any] = {
                        "type": "model_reasoning_summary",
                        "text": final_text,
                    }
                    for key in ("item_id", "response_id", "summary_index"):
                        if payload.get(key) is not None:
                            summary_payload[key] = payload[key]
                    summary_response_id = summary_payload.get("response_id") or response_id
                    await self._persist_model_reasoning_summary(
                        event_name="model_reasoning_summary",
                        payload=summary_payload,
                        session=session,
                        turn_id=turn_id,
                        attempt=event.attempt,
                        response_id=summary_response_id,
                    )
                    reasoning_summary_final_emitted = True
            if event_name == "model_reasoning_summary" and show_reasoning_summary and not reasoning_summary_final_emitted:
                text = payload.get("text")
                if isinstance(text, str) and text:
                    summary_payload: dict[str, Any] = {
                        "type": "model_reasoning_summary",
                        "text": text,
                    }
                    for key in ("item_id", "response_id", "summary_index"):
                        if payload.get(key) is not None:
                            summary_payload[key] = payload[key]
                    summary_response_id = summary_payload.get("response_id") or response_id
                    await self._persist_model_reasoning_summary(
                        event_name="model_reasoning_summary",
                        payload=summary_payload,
                        session=session,
                        turn_id=turn_id,
                        attempt=event.attempt,
                        response_id=summary_response_id,
                    )
                    reasoning_summary_final_emitted = True
            if event_name == "response.completed" and show_reasoning_summary and not reasoning_summary_final_emitted:
                for summary_payload in model_reasoning_summary_stream_payloads(payload):
                    await self._persist_model_reasoning_summary(
                        event_name="model_reasoning_summary",
                        payload=summary_payload,
                        session=session,
                        turn_id=turn_id,
                        attempt=event.attempt,
                        response_id=summary_payload.get("response_id") or response_id,
                    )
                    reasoning_summary_final_emitted = True

        reasoning = {
            "effort": session.effective_runtime_json.get(
                "reasoning_effort",
                self._config.openai.reasoning_effort,
            )
        }
        reasoning_summary = str(
            session.effective_runtime_json.get(
                "reasoning_summary",
                self._config.openai.reasoning_summary,
            )
            or ""
        ).strip()
        if reasoning_summary and reasoning_summary.lower() != "none":
            reasoning["summary"] = reasoning_summary

        request = {
            "model": session.effective_model,
            "instructions": context["instructions"],
            "input": context["input"],
            "tools": context["tool_schema"],
            "parallel_tool_calls": bool(session.effective_runtime_json.get("parallel_tool_calls", False)),
            "reasoning": reasoning,
            "service_tier": session.effective_runtime_json.get("service_tier", self._config.openai.service_tier),
            "on_raw_sse_event": on_raw_sse_event,
        }
        context_management = self._context_management(session=session)
        if context_management:
            request["context_management"] = context_management
        if context.get("include"):
            request["include"] = context["include"]
        if context.get("tool_choice") is not None:
            request["tool_choice"] = context["tool_choice"]
        if not compaction.compacted and use_previous_response_id:
            request["previous_response_id"] = session.latest_response_id
        try:
            response = await self._create_response_with_optional_context_management(request)
        except CancelledModelStreamError:
            return
        except Exception as exc:
            if _is_retryable_model_exception(exc) and event.attempt < self._model_retry_attempts:
                await self._repository.add_stream_event(
                    analysis_id=session.analysis_id,
                    agent_id=session.agent_id,
                    event_type="attempt_failed",
                    payload={
                        "turn_id": str(turn_id),
                        "attempt": event.attempt,
                        "error_code": type(exc).__name__,
                        "message": _safe_error_message(exc),
                        "retryable": True,
                        "supersedes_stream_deltas": True,
                    },
                    turn_id=turn_id,
                    attempt=event.attempt,
                    state="failed",
                )
                raise
            await self._fail_model_call(event=event, session=session, turn_id=turn_id, exc=exc)
            return
        refreshed_session = await self._repository.get_session(session.agent_id)
        if (
            refreshed_session is None
            or refreshed_session.status in TERMINAL_SESSION_STATUSES
            or refreshed_session.status == "cancelling"
        ):
            return
        session = refreshed_session
        output_ref = self._store_model_output(session=session, turn_id=turn_id, response=response)

        if response.tool_calls:
            max_tool_calls = int(session.effective_limits_json.get("max_tool_calls") or 0)
            if max_tool_calls > 0:
                current_tool_calls = await self._count_tool_calls(agent_id=session.agent_id)
                if current_tool_calls + len(response.tool_calls) > max_tool_calls:
                    await self._fail_max_tool_calls_exceeded(
                        event=event,
                        session=session,
                        max_tool_calls=max_tool_calls,
                    )
                    return
            atomic_tool_calls = getattr(self._repository, "complete_turn_with_tool_calls", None)
            await self._handle_tool_calls(
                event=event,
                session=session,
                turn_id=turn_id,
                context=context,
                tool_calls=response.tool_calls,
                completed_turn={
                    "response_id": response.response_id,
                    "previous_response_id": session.latest_response_id,
                    "input_ref": context["input_ref"],
                    "output_ref": output_ref,
                    "usage": response.usage,
                    "output_items": response.output_items,
                }
                if atomic_tool_calls is not None
                else None,
            )
            if atomic_tool_calls is None:
                await self._repository.update_latest_response(
                    agent_id=session.agent_id, response_id=response.response_id
                )
                await self._repository.complete_turn(
                    turn_id=turn_id,
                    response_id=response.response_id,
                    previous_response_id=session.latest_response_id,
                    input_ref=context["input_ref"],
                    output_ref=output_ref,
                    output_text=response.output_text,
                    usage=response.usage,
                )
            return

        completed_event = EventEnvelope.new(
            event_type=EventType.ANALYSIS_COMPLETED,
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            snapshot_id=session.snapshot_id,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload={"response_id": response.response_id, "output_ref": output_ref},
        )
        complete_turn_with_final_answer = getattr(self._repository, "complete_turn_with_final_answer", None)
        if complete_turn_with_final_answer is not None:
            completed = await complete_turn_with_final_answer(
                turn_id=turn_id,
                response_id=response.response_id,
                previous_response_id=session.latest_response_id,
                input_ref=context["input_ref"],
                output_ref=output_ref,
                usage=response.usage,
                latest_response_agent_id=session.agent_id,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                output_text=response.output_text,
                stream_payload={"status": "completed", "response_id": response.response_id, "output_ref": output_ref},
                output_items=response.output_items,
                event=completed_event,
                final_delta_payload={"text": response.output_text} if response.output_text else None,
            )
            if not completed:
                return
            return

        await self._repository.update_latest_response(agent_id=session.agent_id, response_id=response.response_id)
        await self._repository.complete_turn(
            turn_id=turn_id,
            response_id=response.response_id,
            previous_response_id=session.latest_response_id,
            input_ref=context["input_ref"],
            output_ref=output_ref,
            output_text=response.output_text,
            usage=response.usage,
        )
        completed = await self._repository.complete_analysis(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            output_text=response.output_text,
        )
        if not completed:
            return
        if response.output_text:
            await self._repository.add_stream_event(
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                event_type="delta",
                payload={"text": response.output_text},
                turn_id=turn_id,
                response_id=response.response_id,
                state="streaming",
            )
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="done",
            payload={"status": "completed", "response_id": response.response_id, "output_ref": output_ref},
            turn_id=turn_id,
            response_id=response.response_id,
            state="completed",
        )
        await self._repository.add_outbox(completed_event)

    async def _persist_model_reasoning_summary(
        self,
        *,
        event_name: str,
        payload: dict[str, Any],
        session: AgentSessionState,
        turn_id: UUID,
        attempt: int,
        response_id: str | None,
    ) -> None:
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type=event_name,
            payload=payload,
            turn_id=turn_id,
            attempt=attempt,
            response_id=response_id,
        )

    async def _compact_if_needed(
        self, *, event: EventEnvelope, session: AgentSessionState, turn_id: UUID, context: dict[str, Any]
    ) -> CompactionDecision:
        threshold = int(session.effective_limits_json.get("auto_compact_threshold_tokens") or 0)
        token_estimate = int(context.get("token_estimate") or 0)
        if threshold <= 0 or token_estimate <= threshold:
            return CompactionDecision()
        remote_compaction = await self._try_remote_compact(
            event=event,
            session=session,
            turn_id=turn_id,
            context=context,
            token_estimate=token_estimate,
            threshold=threshold,
        )
        if remote_compaction is not None:
            return remote_compaction
        remote_compaction_v2 = await self._try_remote_compact_v2(
            event=event,
            session=session,
            turn_id=turn_id,
            context=context,
            token_estimate=token_estimate,
            threshold=threshold,
        )
        if remote_compaction_v2 is not None:
            return remote_compaction_v2
        local_model_compaction = await self._try_local_model_compact(
            event=event,
            session=session,
            turn_id=turn_id,
            context=context,
            token_estimate=token_estimate,
            threshold=threshold,
        )
        if local_model_compaction is not None:
            return local_model_compaction
        context_items = await self._repository.load_uncompacted_context_items(agent_id=session.agent_id, limit=200)
        summary = await self._compactor.build_summary(session=session, context_items=context_items)
        focus_paths = list(summary.get("focus_paths") or [])
        evidence_ids = list(summary.get("evidence_ids") or [])
        if context_items:
            await self._repository.compact_context_items(
                agent_id=session.agent_id,
                compacted_until_seq=max(int(item.get("seq") or 0) for item in context_items),
                compacted_until_turn=session.turn_count,
                summary_json=summary,
                evidence_ids_json=evidence_ids,
                focus_paths_json=focus_paths,
                next_action=summary["next_action"],
            )
        else:
            await self._repository.add_memory_summary(
                agent_id=session.agent_id,
                compacted_until_turn=session.turn_count,
                summary_json=summary,
                evidence_ids_json=evidence_ids,
                focus_paths_json=focus_paths,
                next_action=summary["next_action"],
            )
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="compact",
            payload={"token_estimate": token_estimate, "threshold": threshold, "strategy": "local"},
            state="completed",
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.AGENT_COMPACTED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={"token_estimate": token_estimate, "threshold": threshold, "strategy": "local"},
            )
        )
        return CompactionDecision(strategy="local")

    async def _try_remote_compact(
        self,
        *,
        event: EventEnvelope,
        session: AgentSessionState,
        turn_id: UUID,
        context: dict[str, Any],
        token_estimate: int,
        threshold: int,
    ) -> CompactionDecision | None:
        try:
            compaction = await self._responses_runner.compact_response(
                {
                    "model": session.effective_model,
                    "input": context["input"],
                }
            )
        except Exception:
            return None
        if not compaction.output:
            return None
        await self._repository.save_compacted_context_window(
            agent_id=session.agent_id,
            turn_id=turn_id,
            compacted_until_turn=session.turn_count,
            compaction_id=compaction.compaction_id,
            output_json=compaction.output,
            usage_json=compaction.usage,
            strategy="remote",
        )
        payload = {
            "token_estimate": token_estimate,
            "threshold": threshold,
            "strategy": "remote",
            "compaction_id": compaction.compaction_id,
        }
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="compact",
            payload=payload,
            turn_id=turn_id,
            state="completed",
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.AGENT_COMPACTED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload=payload,
            )
        )
        return CompactionDecision(strategy="remote", remote_output=compaction.output, replacement_input=compaction.output)

    async def _try_remote_compact_v2(
        self,
        *,
        event: EventEnvelope,
        session: AgentSessionState,
        turn_id: UUID,
        context: dict[str, Any],
        token_estimate: int,
        threshold: int,
    ) -> CompactionDecision | None:
        request = {
            "model": session.effective_model,
            "instructions": context["instructions"],
            "input": [*context["input"], _compaction_trigger_item()],
            "tools": context["tool_schema"],
            "parallel_tool_calls": bool(session.effective_runtime_json.get("parallel_tool_calls", False)),
            "reasoning": {
                "effort": session.effective_runtime_json.get(
                    "reasoning_effort",
                    self._config.openai.reasoning_effort,
                )
            },
            "service_tier": session.effective_runtime_json.get("service_tier", self._config.openai.service_tier),
            "metadata": {"purpose": "remote_compact_v2"},
        }
        if context.get("include"):
            request["include"] = context["include"]
        try:
            response = await self._responses_runner.create_response(request)
        except Exception:
            return None
        replacement_input = _remote_v2_replacement_input(context["input"], response)
        if replacement_input is None:
            return None
        await self._repository.save_compacted_context_window(
            agent_id=session.agent_id,
            turn_id=turn_id,
            compacted_until_turn=session.turn_count,
            compaction_id=response.response_id,
            output_json=replacement_input,
            usage_json=response.usage,
            strategy="remote_v2",
        )
        payload = {
            "token_estimate": token_estimate,
            "threshold": threshold,
            "strategy": "remote_v2",
            "compaction_id": response.response_id,
        }
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="compact",
            payload=payload,
            turn_id=turn_id,
            state="completed",
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.AGENT_COMPACTED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload=payload,
            )
        )
        return CompactionDecision(strategy="remote_v2", replacement_input=replacement_input)

    async def _try_local_model_compact(
        self,
        *,
        event: EventEnvelope,
        session: AgentSessionState,
        turn_id: UUID,
        context: dict[str, Any],
        token_estimate: int,
        threshold: int,
    ) -> CompactionDecision | None:
        request = {
            "model": session.effective_model,
            "instructions": _local_compaction_instructions(self._config),
            "input": [
                *context["input"],
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Compact the preceding DeepDive agent context into a concise, "
                                "machine-resumable state. Preserve completed work, evidence ids, "
                                "open questions, active assumptions, and the next concrete action."
                            ),
                        }
                    ],
                },
            ],
            "tools": [],
            "parallel_tool_calls": False,
            "reasoning": {"effort": session.effective_runtime_json.get("reasoning_effort", self._config.openai.reasoning_effort)},
            "service_tier": session.effective_runtime_json.get("service_tier", self._config.openai.service_tier),
            "metadata": {"purpose": "local_compact"},
        }
        try:
            response = await self._responses_runner.create_response(request)
        except Exception:
            return None
        if not response.output_text.strip() and not response.output_items:
            return None
        replacement_input = _local_model_replacement_input(response)
        await self._repository.save_compacted_context_window(
            agent_id=session.agent_id,
            turn_id=turn_id,
            compacted_until_turn=session.turn_count,
            compaction_id=response.response_id,
            output_json=replacement_input,
            usage_json=response.usage,
            strategy="local_model",
        )
        payload = {
            "token_estimate": token_estimate,
            "threshold": threshold,
            "strategy": "local_model",
            "compaction_id": response.response_id,
        }
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="compact",
            payload=payload,
            turn_id=turn_id,
            state="completed",
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.AGENT_COMPACTED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload=payload,
            )
        )
        return CompactionDecision(strategy="local_model", replacement_input=replacement_input)

    def _context_exceeds_threshold(self, *, session: AgentSessionState, context: dict[str, Any]) -> bool:
        threshold = int(session.effective_limits_json.get("auto_compact_threshold_tokens") or 0)
        token_estimate = int(context.get("token_estimate") or 0)
        return threshold > 0 and token_estimate > threshold

    def _context_management(self, *, session: AgentSessionState) -> list[dict[str, Any]]:
        threshold = int(session.effective_limits_json.get("auto_compact_threshold_tokens") or 0)
        if threshold <= 0:
            return []
        return [{"type": "compaction", "compact_threshold": threshold}]

    async def _create_response_with_optional_context_management(self, request: dict[str, Any]) -> ModelResponse:
        try:
            return await self._responses_runner.create_response(request)
        except Exception as exc:
            if not _is_unsupported_context_management_error(exc) or "context_management" not in request:
                raise
            fallback_request = dict(request)
            fallback_request.pop("context_management", None)
            return await self._responses_runner.create_response(fallback_request)

    async def _tool_output_items(
        self,
        event: EventEnvelope,
        *,
        use_previous_response_id: bool = False,
        ready_tool_outputs: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        outputs = ready_tool_outputs
        if outputs is None:
            outputs = await self._ready_tool_outputs(event)
            if outputs is None:
                return []
        if not outputs:
            return []
        function_outputs = [
            {
                "type": "function_call_output",
                "call_id": output["call_id"],
                "output": output["output"],
            }
            for output in outputs
        ]
        if use_previous_response_id:
            return function_outputs
        output_ref = outputs[0].get("output_ref")
        previous_items = self._previous_output_items(output_ref if isinstance(output_ref, str) else None)
        if previous_items:
            return [*previous_items, *function_outputs]
        items: list[dict[str, Any]] = []
        for output, function_output in zip(outputs, function_outputs, strict=True):
            items.append(
                {
                    "type": "function_call",
                    "call_id": output["call_id"],
                    "name": output["name"],
                    "arguments": json.dumps(output["arguments"], ensure_ascii=False),
                }
            )
            items.append(function_output)
        return items

    async def _ready_tool_outputs(self, event: EventEnvelope) -> list[dict[str, Any]] | None:
        if event.event_type not in {
            EventType.TOOL_CALL_COMPLETED,
            EventType.TOOL_CALL_FAILED,
            EventType.TOOL_CALL_DENIED,
        }:
            return []
        tool_call_id = event.payload.get("tool_call_id")
        if not tool_call_id:
            return []
        output = await self._repository.get_pending_tool_output(tool_call_id=UUID(str(tool_call_id)))
        if output is None and event.event_type in {EventType.TOOL_CALL_FAILED, EventType.TOOL_CALL_DENIED}:
            error = _json_object(event.payload.get("error")) or {}
            fallback_code = "TOOL_DENIED" if event.event_type == EventType.TOOL_CALL_DENIED else "TOOL_FAILED"
            output = {
                "call_id": str(event.payload.get("openai_call_id") or tool_call_id),
                "name": str(event.payload.get("tool_name") or "unknown_tool"),
                "arguments": _json_object(event.payload.get("arguments")) or {},
                "output": json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": str(error.get("code") or fallback_code),
                            "message": str(error.get("message") or "Tool call failed"),
                            "retryable": bool(error.get("retryable", False)),
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        if output is None:
            return None if event.event_type == EventType.TOOL_CALL_COMPLETED else []
        turn_id = output.get("turn_id")
        load_ready_tool_outputs = getattr(self._repository, "load_ready_tool_outputs_for_turn", None)
        if turn_id is not None and load_ready_tool_outputs is not None:
            ready_outputs = await load_ready_tool_outputs(turn_id=UUID(str(turn_id)))
            if ready_outputs is None:
                return None
            return ready_outputs
        return [output]

    def _previous_output_items(self, output_ref: str | None) -> list[dict[str, Any]]:
        if not output_ref:
            return []
        return self._context_assembler.load_model_output_items(output_ref)

    async def _turn_for_trigger(
        self, *, agent_id: UUID, event_id: UUID, trigger_domain_key: str | None
    ) -> dict[str, Any] | None:
        get_turn_for_event = getattr(self._repository, "get_turn_for_event", None)
        if get_turn_for_event is not None:
            turn = await get_turn_for_event(agent_id=agent_id, event_id=event_id)
            if turn is not None:
                return turn
        if trigger_domain_key:
            get_turn_for_domain_key = getattr(self._repository, "get_turn_for_domain_key", None)
            if get_turn_for_domain_key is not None:
                turn = await get_turn_for_domain_key(agent_id=agent_id, trigger_domain_key=trigger_domain_key)
                if turn is not None:
                    return turn
        if await self._repository.has_turn_for_event(agent_id=agent_id, event_id=event_id):
            return {"id": event_id, "status": "completed"}
        return None

    async def _recover_incomplete_turn(
        self, *, event: EventEnvelope, session: AgentSessionState, turn_id: UUID
    ) -> bool:
        get_pending_tool_call_for_turn = getattr(self._repository, "get_pending_tool_call_for_turn", None)
        if get_pending_tool_call_for_turn is None:
            return False
        tool_call = await get_pending_tool_call_for_turn(turn_id=turn_id)
        if tool_call is None:
            return False
        tool_call_id = UUID(str(tool_call["id"]))
        arguments = _json_object(tool_call.get("arguments_json")) or {}
        event_envelope = EventEnvelope.new(
            event_type=EventType.TOOL_CALL_REQUESTED,
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            snapshot_id=UUID(str(tool_call.get("snapshot_id") or session.snapshot_id)),
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload={
                "tool_call_id": str(tool_call_id),
                "openai_call_id": tool_call.get("openai_call_id"),
                "tool_name": tool_call["tool_name"],
                "arguments": arguments,
                "recovered": True,
            },
        )
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="tool_call",
            payload={
                "tool_call_id": str(tool_call_id),
                "tool_name": tool_call["tool_name"],
                "arguments": arguments,
                "recovered": True,
            },
            turn_id=turn_id,
            state="completed",
        )
        await self._repository.add_outbox(event_envelope)
        await self._repository.update_session_status(agent_id=session.agent_id, status="waiting_tool")
        return True

    async def _count_tool_calls(self, *, agent_id: UUID) -> int:
        count_tool_calls = getattr(self._repository, "count_tool_calls", None)
        if count_tool_calls is None:
            return 0
        return int(await count_tool_calls(agent_id=agent_id))

    async def _handle_tool_call(
        self,
        *,
        event: EventEnvelope,
        session: AgentSessionState,
        turn_id: UUID,
        context: dict[str, Any],
        tool_call: ModelToolCall,
        completed_turn: dict[str, Any] | None = None,
    ) -> None:
        if session.snapshot_id is None:
            raise ValueError("Tool call requires snapshot_id")
        previous_result = None
        if _can_reuse_completed_tool_result(tool_call.name):
            previous_result = await self._repository.find_completed_tool_call(
                agent_id=session.agent_id,
                tool_name=tool_call.name,
                arguments_json=tool_call.arguments,
            )
        if previous_result is not None:
            duplicate_result = _previous_tool_result_payload(tool_call=tool_call, previous_result=previous_result)
            event_envelope = EventEnvelope.new(
                event_type=EventType.TOOL_CALL_COMPLETED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={
                    "previous_tool_call_id": str(previous_result["id"]),
                },
            )
            tool_call_kwargs = {
                "agent_id": session.agent_id,
                "turn_id": turn_id,
                "snapshot_id": session.snapshot_id,
                "openai_call_id": tool_call.call_id,
                "tool_name": tool_call.name,
                "arguments_json": tool_call.arguments,
                "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
                "tool_schema_hash": context["tool_schema_hash"],
                "tool_policy_hash": DEFAULT_TOOL_POLICY_HASH,
                "status": "completed",
                "result_summary": duplicate_result,
                "result_ref": previous_result.get("result_ref"),
            }
            stream_payload = duplicate_result
            request_tool_call = getattr(self._repository, "request_tool_call", None)
            complete_turn_with_tool_call = getattr(self._repository, "complete_turn_with_tool_call", None)
            if complete_turn_with_tool_call is not None and completed_turn is not None:
                tool_call_id = await complete_turn_with_tool_call(
                    turn_id=turn_id,
                    response_id=completed_turn["response_id"],
                    previous_response_id=completed_turn["previous_response_id"],
                    input_ref=completed_turn["input_ref"],
                    output_ref=completed_turn["output_ref"],
                    usage=completed_turn["usage"],
                    output_items=completed_turn.get("output_items"),
                    latest_response_agent_id=session.agent_id,
                    tool_call_kwargs=tool_call_kwargs,
                    analysis_id=session.analysis_id,
                    agent_id=session.agent_id,
                    stream_event_type="tool_result",
                    stream_payload=stream_payload,
                    event=event_envelope,
                )
            elif request_tool_call is not None:
                tool_call_id = await request_tool_call(
                    tool_call_kwargs=tool_call_kwargs,
                    analysis_id=session.analysis_id,
                    agent_id=session.agent_id,
                    stream_event_type="tool_result",
                    stream_payload=stream_payload,
                    event=event_envelope,
                )
            else:
                tool_call_id = await self._repository.create_tool_call(**tool_call_kwargs)
                await self._repository.add_stream_event(
                    analysis_id=session.analysis_id,
                    agent_id=session.agent_id,
                    event_type="tool_result",
                    payload=stream_payload,
                    turn_id=turn_id,
                    state="completed",
                )
                event_envelope.payload["tool_call_id"] = str(tool_call_id)
                await self._repository.add_outbox(event_envelope)
            await self._repository.update_session_status(agent_id=session.agent_id, status="waiting_tool")
            event_envelope.payload["tool_call_id"] = str(tool_call_id)
            return
        tool_call_kwargs = {
            "agent_id": session.agent_id,
            "turn_id": turn_id,
            "snapshot_id": session.snapshot_id,
            "openai_call_id": tool_call.call_id,
            "tool_name": tool_call.name,
            "arguments_json": tool_call.arguments,
            "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
            "tool_schema_hash": context["tool_schema_hash"],
            "tool_policy_hash": DEFAULT_TOOL_POLICY_HASH,
            "status": "queued",
        }
        stream_payload = {
            "tool_name": tool_call.name,
            "arguments": tool_call.arguments,
        }
        event_envelope = EventEnvelope.new(
            event_type=EventType.TOOL_CALL_REQUESTED,
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            snapshot_id=session.snapshot_id,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload={
                "openai_call_id": tool_call.call_id,
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        )
        request_tool_call = getattr(self._repository, "request_tool_call", None)
        complete_turn_with_tool_call = getattr(self._repository, "complete_turn_with_tool_call", None)
        if complete_turn_with_tool_call is not None and completed_turn is not None:
            tool_call_id = await complete_turn_with_tool_call(
                turn_id=turn_id,
                response_id=completed_turn["response_id"],
                previous_response_id=completed_turn["previous_response_id"],
                input_ref=completed_turn["input_ref"],
                output_ref=completed_turn["output_ref"],
                usage=completed_turn["usage"],
                output_items=completed_turn.get("output_items"),
                latest_response_agent_id=session.agent_id,
                tool_call_kwargs=tool_call_kwargs,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                stream_event_type="tool_call",
                stream_payload=stream_payload,
                event=event_envelope,
            )
        elif request_tool_call is not None:
            tool_call_id = await request_tool_call(
                tool_call_kwargs=tool_call_kwargs,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                stream_event_type="tool_call",
                stream_payload=stream_payload,
                event=event_envelope,
            )
        else:
            tool_call_id = await self._repository.create_tool_call(**tool_call_kwargs)
            stream_payload["tool_call_id"] = str(tool_call_id)
            await self._repository.add_stream_event(
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                event_type="tool_call",
                payload=stream_payload,
                turn_id=turn_id,
                state="completed",
            )
            event_envelope.payload["tool_call_id"] = str(tool_call_id)
            await self._repository.add_outbox(event_envelope)
        await self._repository.update_session_status(agent_id=session.agent_id, status="waiting_tool")
        stream_payload["tool_call_id"] = str(tool_call_id)
        event_envelope.payload["tool_call_id"] = str(tool_call_id)

    async def _handle_tool_calls(
        self,
        *,
        event: EventEnvelope,
        session: AgentSessionState,
        turn_id: UUID,
        context: dict[str, Any],
        tool_calls: list[ModelToolCall],
        completed_turn: dict[str, Any] | None = None,
    ) -> None:
        if completed_turn is None:
            for tool_call in tool_calls:
                await self._handle_tool_call(
                    event=event,
                    session=session,
                    turn_id=turn_id,
                    context=context,
                    tool_call=tool_call,
                    completed_turn=None,
                )
            return
        tool_call_requests: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            tool_call_requests.append(
                await self._tool_call_request(
                    event=event,
                    session=session,
                    turn_id=turn_id,
                    context=context,
                    tool_call=tool_call,
                )
            )
        complete_turn_with_tool_calls = getattr(self._repository, "complete_turn_with_tool_calls", None)
        if complete_turn_with_tool_calls is None:
            raise RuntimeError("Repository does not support atomic batch tool calls")
        await complete_turn_with_tool_calls(
            turn_id=turn_id,
            response_id=completed_turn["response_id"],
            previous_response_id=completed_turn["previous_response_id"],
            input_ref=completed_turn["input_ref"],
            output_ref=completed_turn["output_ref"],
            usage=completed_turn["usage"],
            output_items=completed_turn.get("output_items"),
            latest_response_agent_id=session.agent_id,
            tool_call_requests=tool_call_requests,
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
        )
        await self._repository.update_session_status(agent_id=session.agent_id, status="waiting_tool")

    async def _tool_call_request(
        self,
        *,
        event: EventEnvelope,
        session: AgentSessionState,
        turn_id: UUID,
        context: dict[str, Any],
        tool_call: ModelToolCall,
    ) -> dict[str, Any]:
        if session.snapshot_id is None:
            raise ValueError("Tool call requires snapshot_id")
        previous_result = None
        if _can_reuse_completed_tool_result(tool_call.name):
            previous_result = await self._repository.find_completed_tool_call(
                agent_id=session.agent_id,
                tool_name=tool_call.name,
                arguments_json=tool_call.arguments,
            )
        if previous_result is not None:
            duplicate_result = _previous_tool_result_payload(tool_call=tool_call, previous_result=previous_result)
            return {
                "tool_call_kwargs": {
                    "agent_id": session.agent_id,
                    "turn_id": turn_id,
                    "snapshot_id": session.snapshot_id,
                    "openai_call_id": tool_call.call_id,
                    "tool_name": tool_call.name,
                    "arguments_json": tool_call.arguments,
                    "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
                    "tool_schema_hash": context["tool_schema_hash"],
                    "tool_policy_hash": DEFAULT_TOOL_POLICY_HASH,
                    "status": "completed",
                    "result_summary": duplicate_result,
                    "result_ref": previous_result.get("result_ref"),
                },
                "stream_event_type": "tool_result",
                "stream_payload": duplicate_result,
                "event": EventEnvelope.new(
                    event_type=EventType.TOOL_CALL_COMPLETED,
                    analysis_id=session.analysis_id,
                    agent_id=session.agent_id,
                    snapshot_id=session.snapshot_id,
                    correlation_id=event.correlation_id,
                    causation_id=event.event_id,
                    payload={"previous_tool_call_id": str(previous_result["id"])},
                ),
            }
        return {
            "tool_call_kwargs": {
                "agent_id": session.agent_id,
                "turn_id": turn_id,
                "snapshot_id": session.snapshot_id,
                "openai_call_id": tool_call.call_id,
                "tool_name": tool_call.name,
                "arguments_json": tool_call.arguments,
                "tool_registry_version": DEFAULT_TOOL_REGISTRY_VERSION,
                "tool_schema_hash": context["tool_schema_hash"],
                "tool_policy_hash": DEFAULT_TOOL_POLICY_HASH,
                "status": "queued",
            },
            "stream_event_type": "tool_call",
            "stream_payload": {
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
            },
            "event": EventEnvelope.new(
                event_type=EventType.TOOL_CALL_REQUESTED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={
                    "openai_call_id": tool_call.call_id,
                    "tool_name": tool_call.name,
                    "arguments": tool_call.arguments,
                },
            ),
        }

    def _store_model_output(self, *, session: AgentSessionState, turn_id: UUID, response: ModelResponse) -> str:
        return self._context_assembler.store_model_output(session=session, turn_id=turn_id, response=response)

    async def _fail_max_turns_exceeded(self, *, event: EventEnvelope, session: AgentSessionState) -> None:
        message = f"Agent reached max_turns={session.max_turns} before producing a final answer."
        failed = await self._repository.fail_analysis(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            error_code="MAX_TURNS_EXCEEDED",
            error_message=message,
        )
        if not failed:
            return
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="error",
            payload={
                "error_code": "MAX_TURNS_EXCEEDED",
                "error_message": message,
                "turn_count": session.turn_count,
                "max_turns": session.max_turns,
            },
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_FAILED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={
                    "error_code": "MAX_TURNS_EXCEEDED",
                    "error_message": message,
                    "turn_count": session.turn_count,
                    "max_turns": session.max_turns,
                },
            )
        )

    async def _fail_max_tool_calls_exceeded(
        self, *, event: EventEnvelope, session: AgentSessionState, max_tool_calls: int
    ) -> None:
        message = f"Agent reached max_tool_calls={max_tool_calls} before producing a final answer."
        failed = await self._repository.fail_analysis(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            error_code="MAX_TOOL_CALLS_EXCEEDED",
            error_message=message,
        )
        if not failed:
            return
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="error",
            payload={
                "error_code": "MAX_TOOL_CALLS_EXCEEDED",
                "error_message": message,
                "turn_count": session.turn_count,
                "max_tool_calls": max_tool_calls,
            },
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_FAILED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={
                    "error_code": "MAX_TOOL_CALLS_EXCEEDED",
                    "error_message": message,
                    "turn_count": session.turn_count,
                    "max_tool_calls": max_tool_calls,
                },
            )
        )

    async def _fail_model_call(
        self, *, event: EventEnvelope, session: AgentSessionState, turn_id: UUID, exc: Exception
    ) -> None:
        message = _safe_error_message(exc)
        await self._repository.fail_turn(turn_id=turn_id, error_code="MODEL_CALL_FAILED", error_message=message)
        failed = await self._repository.fail_analysis(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            error_code="MODEL_CALL_FAILED",
            error_message=message,
        )
        if not failed:
            return
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="error",
            payload={
                "error_code": "MODEL_CALL_FAILED",
                "error_message": message,
                "turn_count": session.turn_count,
            },
            turn_id=turn_id,
            state="failed",
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_FAILED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={
                    "error_code": "MODEL_CALL_FAILED",
                    "error_message": message,
                    "turn_count": session.turn_count,
                },
            )
        )

    async def _fail_context_too_large_after_compact(
        self,
        *,
        event: EventEnvelope,
        session: AgentSessionState,
        turn_id: UUID,
        context: dict[str, Any],
    ) -> None:
        threshold = int(session.effective_limits_json.get("auto_compact_threshold_tokens") or 0)
        token_estimate = int(context.get("token_estimate") or 0)
        message = (
            f"Context token estimate {token_estimate} still exceeds "
            f"auto_compact_threshold_tokens={threshold} after compaction."
        )
        await self._repository.fail_turn(
            turn_id=turn_id, error_code="CONTEXT_TOO_LARGE_AFTER_COMPACT", error_message=message
        )
        failed = await self._repository.fail_analysis(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            error_code="CONTEXT_TOO_LARGE_AFTER_COMPACT",
            error_message=message,
        )
        if not failed:
            return
        payload = {
            "error_code": "CONTEXT_TOO_LARGE_AFTER_COMPACT",
            "error_message": message,
            "token_estimate": token_estimate,
            "threshold": threshold,
        }
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="error",
            payload=payload,
            turn_id=turn_id,
            state="failed",
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_FAILED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload=payload,
            )
        )

    async def _fail_unrecoverable_turn_replay(
        self, *, event: EventEnvelope, session: AgentSessionState, turn_id: UUID
    ) -> None:
        message = (
            "Agent turn was replayed while an earlier attempt for the same event was not completed; "
            "automatic recovery for partial model calls is not available yet."
        )
        await self._repository.fail_turn(
            turn_id=turn_id,
            error_code="AGENT_TURN_RECOVERY_REQUIRED",
            error_message=message,
        )
        failed = await self._repository.fail_analysis(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            error_code="AGENT_TURN_RECOVERY_REQUIRED",
            error_message=message,
        )
        if not failed:
            return
        await self._repository.add_stream_event(
            analysis_id=session.analysis_id,
            agent_id=session.agent_id,
            event_type="error",
            payload={
                "error_code": "AGENT_TURN_RECOVERY_REQUIRED",
                "error_message": message,
            },
            turn_id=turn_id,
            state="failed",
        )
        await self._repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.ANALYSIS_FAILED,
                analysis_id=session.analysis_id,
                agent_id=session.agent_id,
                snapshot_id=session.snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={
                    "error_code": "AGENT_TURN_RECOVERY_REQUIRED",
                    "error_message": message,
                },
            )
        )


TERMINAL_SESSION_STATUSES = {"completed", "failed", "cancelled"}


def _safe_error_message(exc: Exception) -> str:
    message = str(exc) or type(exc).__name__
    return message[:4096]


def _local_compaction_instructions(config: AppConfig) -> str:
    configured = (config.prompt.compaction_instruction or "").strip()
    if configured:
        return configured
    return (
        "You are compacting a DeepDive agent transcript. Return only the state needed to resume the task: "
        "goal, completed steps, confirmed facts with evidence ids, active hypotheses, open questions, focus paths, "
        "and next action. Do not restart the analysis."
    )


def _local_model_replacement_input(response: ModelResponse) -> list[dict[str, Any]]:
    if response.output_items:
        return list(response.output_items)
    return [
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Compacted DeepDive context state:\n" + response.output_text.strip(),
                }
            ],
        }
    ]


def _remote_v2_replacement_input(
    prompt_input: list[dict[str, Any]],
    response: ModelResponse,
) -> list[dict[str, Any]] | None:
    output_items = response.output_items or []
    compaction_items = [item for item in output_items if item.get("type") == "compaction"]
    if len(compaction_items) != 1:
        return None
    retained = [_canonical_remote_v2_retained_message(item) for item in prompt_input if _is_remote_v2_retained_message(item)]
    return [*retained, compaction_items[0]]


def _is_remote_v2_retained_message(item: dict[str, Any]) -> bool:
    if item.get("type") == "message":
        return item.get("role") in {"user", "developer", "system"}
    if item.get("type") is None and "role" in item:
        return item.get("role") in {"user", "developer", "system"}
    return False


def _canonical_remote_v2_retained_message(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") == "message":
        return dict(item)
    return {"type": "message", **item}


def _compaction_trigger_item() -> dict[str, str]:
    return {"type": "compaction_trigger"}


def _previous_tool_result_payload(*, tool_call: ModelToolCall, previous_result: dict[str, Any]) -> dict[str, Any]:
    result_summary = previous_result.get("result_summary")
    if isinstance(result_summary, str):
        try:
            payload = _json_object(json.loads(result_summary)) or {
                "ok": True,
                "tool_name": tool_call.name,
                "result": result_summary,
            }
        except json.JSONDecodeError:
            payload = {"ok": True, "tool_name": tool_call.name, "result": result_summary}
    elif isinstance(result_summary, dict):
        payload = dict(cast(dict[str, Any], result_summary))
    else:
        payload = {"ok": True, "tool_name": tool_call.name, "result": result_summary}
    payload.setdefault("ok", True)
    payload.setdefault("tool_name", tool_call.name)
    payload["reused_from_tool_call_id"] = str(previous_result["id"])
    if previous_result.get("result_ref") and "result_ref" not in payload:
        payload["result_ref"] = previous_result["result_ref"]
    return payload


def _json_object(value: Any) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _can_reuse_completed_tool_result(tool_name: str) -> bool:
    return tool_name in {"list_files", "search_file", "search_text", "read_file"}


def _is_retryable_model_turn(turn: dict[str, Any]) -> bool:
    return str(turn.get("status") or "") in {"calling_model", "assembling_context", "streaming"}


def _is_retryable_model_exception(exc: Exception) -> bool:
    if type(exc).__name__ == "IncompleteResponseStreamError":
        return True
    message = _safe_error_message(exc).lower()
    retryable_markers = (
        "429",
        "rate_limit",
        "rate limit",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "remote end closed",
        "ended before response.completed",
        "incomplete stream",
        "502",
        "503",
        "504",
    )
    return any(marker in message for marker in retryable_markers)


def _is_unsupported_context_management_error(exc: Exception) -> bool:
    message = _safe_error_message(exc).lower()
    return "context_management" in message and any(
        marker in message
        for marker in (
            "unknown",
            "unsupported",
            "unrecognized",
            "invalid",
            "unexpected",
            "not supported",
        )
    )


def _is_terminal_tool_event(event: EventEnvelope) -> bool:
    return event.event_type in {EventType.TOOL_CALL_COMPLETED, EventType.TOOL_CALL_FAILED, EventType.TOOL_CALL_DENIED}


def _trigger_domain_key(event: EventEnvelope) -> str | None:
    if event.event_type == EventType.SNAPSHOT_READY and event.snapshot_id is not None:
        return f"{event.event_type.value}:{event.snapshot_id}"
    if event.event_type in {EventType.TOOL_CALL_COMPLETED, EventType.TOOL_CALL_FAILED, EventType.TOOL_CALL_DENIED}:
        tool_call_id = event.payload.get("tool_call_id")
        if tool_call_id:
            return f"ToolCallTerminal:{tool_call_id}"
    if event.event_type == EventType.AGENT_CONTINUE_REQUESTED:
        reason = event.payload.get("reason")
        if reason:
            return f"{event.event_type.value}:{reason}"
    return None
