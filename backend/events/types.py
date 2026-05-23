from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    ANALYSIS_REQUESTED = "AnalysisRequested"
    ANALYSIS_CANCEL_REQUESTED = "AnalysisCancelRequested"
    SNAPSHOT_REQUESTED = "SnapshotRequested"
    SNAPSHOT_STARTED = "SnapshotStarted"
    SNAPSHOT_READY = "SnapshotReady"
    SNAPSHOT_FAILED = "SnapshotFailed"
    AGENT_CONTINUE_REQUESTED = "AgentContinueRequested"
    AGENT_STARTED = "AgentStarted"
    AGENT_WAITING_FOR_TOOL = "AgentWaitingForTool"
    AGENT_COMPACTED = "AgentCompacted"
    ANALYSIS_COMPLETED = "AnalysisCompleted"
    ANALYSIS_FAILED = "AnalysisFailed"
    ANALYSIS_CANCELLED = "AnalysisCancelled"
    TOOL_CALL_REQUESTED = "ToolCallRequested"
    TOOL_CALL_STARTED = "ToolCallStarted"
    TOOL_CALL_COMPLETED = "ToolCallCompleted"
    TOOL_CALL_FAILED = "ToolCallFailed"
    TOOL_CALL_DENIED = "ToolCallDenied"
    EVENT_PROCESSING_FAILED = "EventProcessingFailed"
