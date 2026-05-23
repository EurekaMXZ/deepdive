from __future__ import annotations

import json
import contextlib
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID


LIVE_MODEL_STREAM_TOPIC = "deepdive.agent.stream"


class LiveModelStreamProducer(Protocol):
    async def send_and_wait(self, topic: str, *, key: bytes, value: bytes) -> object:
        ...


@dataclass(frozen=True)
class LiveModelStreamEvent:
    schema_version: int
    analysis_id: UUID
    agent_id: UUID
    turn_id: UUID
    attempt: int
    stream_seq: int
    event_name: str
    payload: dict[str, Any]
    response_id: str | None
    occurred_at: datetime

    @classmethod
    def new(
        cls,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        turn_id: UUID,
        attempt: int,
        stream_seq: int,
        event_name: str,
        payload: dict[str, Any],
        response_id: str | None = None,
    ) -> "LiveModelStreamEvent":
        return cls(
            schema_version=1,
            analysis_id=analysis_id,
            agent_id=agent_id,
            turn_id=turn_id,
            attempt=attempt,
            stream_seq=stream_seq,
            event_name=event_name,
            payload=dict(payload),
            response_id=response_id,
            occurred_at=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "analysis_id": str(self.analysis_id),
            "agent_id": str(self.agent_id),
            "turn_id": str(self.turn_id),
            "attempt": self.attempt,
            "stream_seq": self.stream_seq,
            "event_name": self.event_name,
            "payload": self.payload,
            "response_id": self.response_id,
            "occurred_at": self.occurred_at.isoformat(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str | bytes) -> "LiveModelStreamEvent":
        if isinstance(value, bytes):
            value = value.decode()
        return cls.from_dict(json.loads(value))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveModelStreamEvent":
        return cls(
            schema_version=int(data["schema_version"]),
            analysis_id=UUID(data["analysis_id"]),
            agent_id=UUID(data["agent_id"]),
            turn_id=UUID(data["turn_id"]),
            attempt=int(data["attempt"]),
            stream_seq=int(data["stream_seq"]),
            event_name=str(data["event_name"]),
            payload=dict(data.get("payload") or {}),
            response_id=data.get("response_id"),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
        )


def live_model_stream_key(event: LiveModelStreamEvent) -> bytes:
    return str(event.analysis_id).encode()


def completed_live_payload(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("response") if isinstance(payload, dict) else None
    response_id = response.get("id") if isinstance(response, dict) else payload.get("response_id")
    result = {"type": "response.completed"}
    if response_id:
        result["response_id"] = response_id
    return result


def model_reasoning_summary_text_live_payload(
    event_name: str,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    if event_name == "response.reasoning_summary_text.delta":
        event_type = "model_reasoning_summary.delta"
        text = payload.get("delta")
    elif event_name == "response.reasoning_summary_text.done":
        event_type = "model_reasoning_summary.done"
        text = payload.get("text")
    else:
        return None
    if not isinstance(text, str) or not text:
        return None

    live_payload: dict[str, Any] = {
        "type": event_type,
        "text": text,
    }
    for key in ("item_id", "response_id", "summary_index"):
        if payload.get(key) is not None:
            live_payload[key] = payload[key]
    return event_type, live_payload


def model_reasoning_summary_live_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        return []
    response_id = response.get("id") if response.get("id") is not None else payload.get("response_id")
    output = response.get("output")
    if not isinstance(output, list):
        return []

    summaries: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "reasoning":
            continue
        summary_parts = item.get("summary")
        if not isinstance(summary_parts, list):
            continue
        for summary in summary_parts:
            if not isinstance(summary, dict) or summary.get("type") != "summary_text":
                continue
            text = summary.get("text")
            if not isinstance(text, str) or not text:
                continue
            live_payload: dict[str, Any] = {
                "type": "model_reasoning_summary",
                "text": text,
            }
            if item.get("id") is not None:
                live_payload["item_id"] = str(item["id"])
            if response_id is not None:
                live_payload["response_id"] = str(response_id)
            summaries.append(live_payload)
    return summaries


class KafkaLiveModelStreamPublisher:
    def __init__(
        self,
        producer: LiveModelStreamProducer,
        *,
        queue_size: int = 1000,
    ) -> None:
        self._producer = producer
        self._queue: asyncio.Queue[LiveModelStreamEvent | None] = asyncio.Queue(maxsize=max(1, int(queue_size)))
        self._task: asyncio.Task | None = None
        self.dropped_events = 0

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._queue.put(None)
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def publish(self, event: LiveModelStreamEvent) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self.dropped_events += 1
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped_events += 1

    async def publish_event(
        self,
        *,
        analysis_id: UUID,
        agent_id: UUID,
        turn_id: UUID,
        attempt: int,
        stream_seq: int,
        event_name: str,
        payload: dict[str, Any],
        response_id: str | None = None,
    ) -> None:
        await self.publish(
            LiveModelStreamEvent.new(
                analysis_id=analysis_id,
                agent_id=agent_id,
                turn_id=turn_id,
                attempt=attempt,
                stream_seq=stream_seq,
                event_name=event_name,
                payload=payload,
                response_id=response_id,
            )
        )

    async def flush(self) -> None:
        await self._queue.join()

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                if event is None:
                    return
                await self._producer.send_and_wait(
                    LIVE_MODEL_STREAM_TOPIC,
                    key=live_model_stream_key(event),
                    value=event.to_json().encode(),
                )
            finally:
                self._queue.task_done()
