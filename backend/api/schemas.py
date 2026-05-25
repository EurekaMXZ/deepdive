from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class AnalysisCreateRequest(BaseModel):
    repository_url: HttpUrl
    ref: str = Field(min_length=1)
    analysis_profile_id: UUID | None = None

    @field_validator("repository_url")
    @classmethod
    def reject_repository_url_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("repository_url must not contain credentials")
        parsed = urlsplit(str(value))
        if parsed.query or parsed.fragment:
            raise ValueError("repository_url must not contain query or fragment")
        return value

    @field_validator("analysis_profile_id")
    @classmethod
    def reject_unregistered_profile_id(cls, value: UUID | None) -> UUID | None:
        if value is not None:
            raise ValueError("analysis_profile_id is not supported until backend profile registry is enabled")
        return value


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: UUID
    agent_id: UUID
    snapshot_id: UUID | None
    status: str
    repository_url: str
    requested_ref: str
    resolved_commit_sha: str | None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisCreateResponse(BaseModel):
    analysis_id: UUID
    agent_id: UUID
    snapshot_id: UUID | None
    status: str
    created_at: datetime


class AnalysisListResponse(BaseModel):
    items: list[AnalysisResponse]
    next_cursor: str | None = None


class AnalysisSuggestionResponse(BaseModel):
    analysis_id: UUID
    agent_id: UUID
    snapshot_id: UUID | None
    status: str
    repository_label: str
    repository_url: str
    requested_ref: str
    resolved_commit_sha: str | None
    updated_at: datetime


class AnalysisSuggestionListResponse(BaseModel):
    items: list[AnalysisSuggestionResponse]


class RepositorySearchResponse(BaseModel):
    repository_label: str
    repository_url: str
    latest_analysis_id: UUID
    latest_status: str
    latest_requested_ref: str
    latest_resolved_commit_sha: str | None
    analysis_count: int
    completed_analysis_count: int
    last_analyzed_at: datetime


class RepositorySearchListResponse(BaseModel):
    items: list[RepositorySearchResponse]


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: UUID


class ErrorResponse(BaseModel):
    error: ErrorBody
