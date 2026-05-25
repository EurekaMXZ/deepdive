from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def validate_repository_url(value: HttpUrl) -> HttpUrl:
    if value.username or value.password:
        raise ValueError("repository_url must not contain credentials")
    parsed = urlsplit(str(value))
    if parsed.query or parsed.fragment:
        raise ValueError("repository_url must not contain query or fragment")
    return value


def validate_analysis_profile_id(value: UUID | None) -> UUID | None:
    if value is not None:
        raise ValueError("analysis_profile_id is not supported until backend profile registry is enabled")
    return value


class AnalysisCreateRequest(BaseModel):
    repository_url: HttpUrl
    ref: str = Field(min_length=1)
    analysis_profile_id: UUID | None = None

    @field_validator("repository_url")
    @classmethod
    def reject_repository_url_credentials(cls, value: HttpUrl) -> HttpUrl:
        return validate_repository_url(value)

    @field_validator("analysis_profile_id")
    @classmethod
    def reject_unregistered_profile_id(cls, value: UUID | None) -> UUID | None:
        return validate_analysis_profile_id(value)


class AnalysisBatchCreateItemRequest(BaseModel):
    repository_url: HttpUrl
    ref: str = Field(min_length=1)
    analysis_profile_id: UUID | None = None

    @field_validator("repository_url")
    @classmethod
    def reject_repository_url_credentials(cls, value: HttpUrl) -> HttpUrl:
        return validate_repository_url(value)

    @field_validator("analysis_profile_id")
    @classmethod
    def reject_unregistered_profile_id(cls, value: UUID | None) -> UUID | None:
        return validate_analysis_profile_id(value)


class AnalysisBatchCreateRequest(BaseModel):
    items: list[AnalysisBatchCreateItemRequest] = Field(min_length=1, max_length=100)
    max_parallel: int = Field(ge=1, le=20)


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


class AnalysisBatchItemResponse(BaseModel):
    batch_item_id: UUID
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


class AnalysisBatchCreateResponse(BaseModel):
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
    items: list[AnalysisBatchItemResponse]


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
