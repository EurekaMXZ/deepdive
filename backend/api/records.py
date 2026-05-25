from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
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
    tenant_id: UUID | None = None
    created_by_user_id: UUID | None = None


@dataclass(frozen=True)
class AnalysisBatchCreateItem:
    repository_url: str
    requested_ref: str
    analysis_profile_id: UUID | None = None


@dataclass
class AnalysisBatchItemRecord:
    batch_item_id: UUID
    batch_id: UUID
    analysis_id: UUID
    agent_id: UUID
    repository_url: str
    requested_ref: str
    status: str
    sort_order: int
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class AnalysisBatchRecord:
    batch_id: UUID
    status: str
    max_parallel: int
    total_count: int
    pending_count: int
    active_count: int
    completed_count: int
    failed_count: int
    cancelled_count: int
    created_at: datetime
    updated_at: datetime
    items: list[AnalysisBatchItemRecord]
    tenant_id: UUID | None = None
    created_by_user_id: UUID | None = None


@dataclass
class AgentStreamEventRecord:
    seq: int
    event_type: str
    payload_json: dict[str, Any]


@dataclass
class RepositorySearchRecord:
    repository_url: str
    repository_label: str
    latest_analysis_id: UUID
    latest_status: str
    latest_requested_ref: str
    latest_resolved_commit_sha: str | None
    analysis_count: int
    completed_analysis_count: int
    last_analyzed_at: datetime
