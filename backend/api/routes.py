from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import datetime
from typing import Annotated, Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from backend.api.auth_dependencies import require_permission
from backend.api.schemas import (
    AnalysisCreateRequest,
    AnalysisCreateResponse,
    AnalysisListResponse,
    AnalysisResponse,
    AnalysisSuggestionListResponse,
    AnalysisSuggestionResponse,
    ErrorResponse,
)
from backend.api.services import AnalysisRecord, encode_list_cursor, maybe_await
from backend.api.sse import (
    StreamEvent,
    event_seq,
    format_sse_event,
    is_terminal_stream_event,
    parse_last_event_id,
)
from backend.api.stream_schemas import TERMINAL_ANALYSIS_STATUSES
from backend.auth import CurrentUser
from backend.ids import new_uuid7


class AnalysisService(Protocol):
    supports_live_events: bool

    def create(
        self,
        *,
        repository_url: str,
        requested_ref: str,
        analysis_profile_id: UUID | None = None,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord: ...

    def list(
        self,
        *,
        status: str | None = None,
        repository_url_hash: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[AnalysisRecord]: ...

    def suggest(
        self,
        *,
        repository_query: str,
        limit: int = 6,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> list[AnalysisRecord]: ...

    def get(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord | None: ...

    def cancel(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> AnalysisRecord | None: ...

    def stream_events(
        self,
        analysis_id: UUID,
        *,
        after_seq: int = 0,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> Iterable[StreamEvent | dict[str, Any]]: ...

    def analysis_status(
        self,
        analysis_id: UUID,
        *,
        tenant_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> str | None: ...


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


router = APIRouter()


@router.post(
    "/analysis",
    response_model=AnalysisCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_analysis(
    body: AnalysisCreateRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("analysis:create"))],
) -> AnalysisCreateResponse:
    record = await maybe_await(
        service.create(
            repository_url=str(body.repository_url),
            requested_ref=body.ref,
            analysis_profile_id=body.analysis_profile_id,
            tenant_id=current_user.tenant_id,
            created_by_user_id=current_user.id,
        )
    )
    return AnalysisCreateResponse(
        analysis_id=record.analysis_id,
        agent_id=record.agent_id,
        snapshot_id=record.snapshot_id,
        status=record.status,
        created_at=record.created_at,
    )


@router.get("/analysis", response_model=AnalysisListResponse)
async def list_analysis(
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("analysis:read"))],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    repository_url_hash: Annotated[str | None, Query()] = None,
    created_after: Annotated[datetime | None, Query()] = None,
    created_before: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> AnalysisListResponse:
    records = await maybe_await(
        service.list(
            status=status_filter,
            repository_url_hash=repository_url_hash,
            created_after=created_after,
            created_before=created_before,
            limit=limit + 1,
            cursor=cursor,
            tenant_id=current_user.tenant_id,
            created_by_user_id=current_user.id,
        )
    )
    page = records[:limit]
    next_cursor = encode_list_cursor(page[-1]) if len(records) > limit and page else None
    return AnalysisListResponse(
        items=[_to_response(record) for record in page],
        next_cursor=next_cursor,
    )


@router.get("/analysis/suggestions", response_model=AnalysisSuggestionListResponse)
async def suggest_analysis(
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("analysis:read"))],
    repository_query: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=10)] = 6,
) -> AnalysisSuggestionListResponse:
    records = await maybe_await(
        service.suggest(
            repository_query=repository_query,
            limit=limit,
            tenant_id=current_user.tenant_id,
            created_by_user_id=current_user.id,
        )
    )
    return AnalysisSuggestionListResponse(items=[_to_suggestion(record) for record in records])


@router.get(
    "/analysis/{analysis_id}",
    response_model=AnalysisResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_analysis(
    analysis_id: UUID,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("analysis:read"))],
) -> AnalysisResponse:
    record = await maybe_await(
        service.get(analysis_id, tenant_id=current_user.tenant_id, created_by_user_id=current_user.id)
    )
    if record is None:
        raise _not_found()
    return _to_response(record)


@router.post(
    "/analysis/{analysis_id}/cancel",
    response_model=AnalysisResponse,
    responses={404: {"model": ErrorResponse}},
)
async def cancel_analysis(
    analysis_id: UUID,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("analysis:cancel"))],
) -> AnalysisResponse:
    record = await maybe_await(
        service.cancel(analysis_id, tenant_id=current_user.tenant_id, created_by_user_id=current_user.id)
    )
    if record is None:
        raise _not_found()
    return _to_response(record)


@router.get(
    "/analysis/{analysis_id}/events",
    responses={404: {"model": ErrorResponse}},
)
async def stream_analysis_events(
    analysis_id: UUID,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("analysis:events"))],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    poll_interval_seconds: Annotated[float, Query(ge=0, le=10)] = 0.2,
    idle_timeout_seconds: Annotated[float, Query(ge=0, le=300)] = 30.0,
    debug_raw_llm_events: Annotated[bool, Query()] = False,
) -> StreamingResponse:
    del debug_raw_llm_events
    record = await maybe_await(
        service.get(analysis_id, tenant_id=current_user.tenant_id, created_by_user_id=current_user.id)
    )
    if record is None:
        raise _not_found()
    after_seq = parse_last_event_id(last_event_id)
    if service.supports_live_events:
        return StreamingResponse(
            _polling_sse_event_records(
                service,
                analysis_id,
                after_seq=after_seq,
                tenant_id=current_user.tenant_id,
                created_by_user_id=current_user.id,
                poll_interval_seconds=poll_interval_seconds,
                idle_timeout_seconds=idle_timeout_seconds,
            ),
            media_type="text/event-stream",
        )
    events = await maybe_await(
        service.stream_events(
            analysis_id,
            after_seq=after_seq,
            tenant_id=current_user.tenant_id,
            created_by_user_id=current_user.id,
        )
    )
    return StreamingResponse(_sse_event_records(events), media_type="text/event-stream")


def _to_response(record: AnalysisRecord) -> AnalysisResponse:
    return AnalysisResponse(
        analysis_id=record.analysis_id,
        agent_id=record.agent_id,
        snapshot_id=record.snapshot_id,
        status=record.status,
        repository_url=record.repository_url,
        requested_ref=record.requested_ref,
        resolved_commit_sha=record.resolved_commit_sha,
        error_code=record.error_code,
        error_message=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _to_suggestion(record: AnalysisRecord) -> AnalysisSuggestionResponse:
    return AnalysisSuggestionResponse(
        analysis_id=record.analysis_id,
        agent_id=record.agent_id,
        snapshot_id=record.snapshot_id,
        status=record.status,
        repository_label=_repository_label(record.repository_url),
        repository_url=record.repository_url,
        requested_ref=record.requested_ref,
        resolved_commit_sha=record.resolved_commit_sha,
        updated_at=record.updated_at,
    )


def _repository_label(repository_url: str) -> str:
    parsed = urlsplit(repository_url)
    if parsed.hostname == "github.com":
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path.removesuffix(".git")
        if path.count("/") == 1:
            return path
    return repository_url


def _sse_event_records(events: Iterable[StreamEvent | dict[str, Any]]) -> Iterator[str]:
    for event in events:
        yield _format_sse_event(event)


async def _polling_sse_event_records(
    service: AnalysisService,
    analysis_id: UUID,
    *,
    after_seq: int,
    poll_interval_seconds: float,
    idle_timeout_seconds: float,
    tenant_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
) -> AsyncIterator[str]:
    last_seq = after_seq
    loop = asyncio.get_running_loop()
    idle_deadline = loop.time() + idle_timeout_seconds
    while True:
        events = await maybe_await(
            service.stream_events(
                analysis_id,
                after_seq=last_seq,
                tenant_id=tenant_id,
                created_by_user_id=created_by_user_id,
            )
        )
        emitted = False
        terminal_event_seen = False
        for event in events:
            seq = event_seq(event)
            last_seq = max(last_seq, seq)
            emitted = True
            terminal_event_seen = is_terminal_stream_event(event) or terminal_event_seen
            yield format_sse_event(event)

        if emitted:
            idle_deadline = loop.time() + idle_timeout_seconds
        if terminal_event_seen:
            return

        current_status = await maybe_await(
            service.analysis_status(analysis_id, tenant_id=tenant_id, created_by_user_id=created_by_user_id)
        )
        if current_status in TERMINAL_ANALYSIS_STATUSES:
            events = await maybe_await(
                service.stream_events(
                    analysis_id,
                    after_seq=last_seq,
                    tenant_id=tenant_id,
                    created_by_user_id=created_by_user_id,
                )
            )
            for event in events:
                seq = event_seq(event)
                last_seq = max(last_seq, seq)
                terminal_event_seen = is_terminal_stream_event(event) or terminal_event_seen
                yield format_sse_event(event)
            if terminal_event_seen:
                return
            return
        if loop.time() >= idle_deadline:
            yield ": keepalive\n\n"
            idle_deadline = loop.time() + idle_timeout_seconds
        if poll_interval_seconds > 0:
            await asyncio.sleep(poll_interval_seconds)
        else:
            await asyncio.sleep(0)


def _format_sse_event(event: StreamEvent | dict[str, Any]) -> str:
    return format_sse_event(event)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": {
                "code": "ANALYSIS_NOT_FOUND",
                "message": "Analysis does not exist.",
                "request_id": str(new_uuid7()),
            }
        },
    )


def api_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "request_id": str(new_uuid7()),
            }
        },
    )
