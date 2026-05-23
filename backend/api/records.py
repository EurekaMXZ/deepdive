from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class AnalysisRecord:
    analysis_id: UUID
    agent_id: UUID
    snapshot_id: UUID | None
    status: str
    repository_url: str
    requested_ref: str
    resolved_commit_sha: str | None
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class AgentStreamEventRecord:
    seq: int
    event_type: str
    payload_json: dict
