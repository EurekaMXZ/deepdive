from __future__ import annotations

from backend.events.envelope import EventEnvelope
from backend.events.types import EventType

ANALYSIS_COMMAND_TOPICS: dict[EventType, str] = {
    EventType.ANALYSIS_REQUESTED: "deepdive.analysis.commands",
    EventType.ANALYSIS_CANCEL_REQUESTED: "deepdive.analysis.commands",
}

ANALYSIS_BATCH_SCHEDULER_COMMAND_TOPICS: dict[EventType, str] = {
    EventType.ANALYSIS_BATCH_SUBMITTED: "deepdive.analysis-batch.commands",
    EventType.ANALYSIS_BATCH_SLOT_AVAILABLE: "deepdive.analysis-batch.commands",
    EventType.ANALYSIS_COMPLETED: "deepdive.analysis-batch.commands",
    EventType.ANALYSIS_FAILED: "deepdive.analysis-batch.commands",
    EventType.ANALYSIS_CANCELLED: "deepdive.analysis-batch.commands",
}

SNAPSHOT_COMMAND_TOPICS: dict[EventType, str] = {
    EventType.SNAPSHOT_REQUESTED: "deepdive.snapshot.commands",
}

AGENT_INBOX_TOPICS: dict[EventType, str] = {
    EventType.SNAPSHOT_READY: "deepdive.agent.commands",
    EventType.AGENT_CONTINUE_REQUESTED: "deepdive.agent.commands",
    EventType.TOOL_CALL_COMPLETED: "deepdive.agent.commands",
    EventType.TOOL_CALL_FAILED: "deepdive.agent.commands",
    EventType.TOOL_CALL_DENIED: "deepdive.agent.commands",
}

EXECUTION_COMMAND_TOPICS: dict[EventType, str] = {
    EventType.TOOL_CALL_REQUESTED: "deepdive.execution.commands",
}

COMMAND_TOPICS: dict[EventType, str] = {
    **ANALYSIS_COMMAND_TOPICS,
    **ANALYSIS_BATCH_SCHEDULER_COMMAND_TOPICS,
    **SNAPSHOT_COMMAND_TOPICS,
    **AGENT_INBOX_TOPICS,
    **EXECUTION_COMMAND_TOPICS,
}

STREAM_TOPICS: dict[EventType, str] = {}

DLQ_TOPICS: dict[EventType, str] = {
    EventType.EVENT_PROCESSING_FAILED: "deepdive.dlq",
}


def event_topic(event: EventEnvelope) -> str:
    if event.event_type in COMMAND_TOPICS:
        return COMMAND_TOPICS[event.event_type]
    if event.event_type in STREAM_TOPICS:
        return STREAM_TOPICS[event.event_type]
    if event.event_type in DLQ_TOPICS:
        return DLQ_TOPICS[event.event_type]
    return "deepdive.domain.events"


def event_key(event: EventEnvelope) -> str:
    if event.event_type in {
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_COMPLETED,
        EventType.TOOL_CALL_FAILED,
        EventType.TOOL_CALL_DENIED,
    }:
        tool_call_id = event.payload.get("tool_call_id")
        if tool_call_id:
            return str(tool_call_id)
    if event.analysis_id is not None:
        return str(event.analysis_id)
    return str(event.correlation_id)
