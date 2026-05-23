from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from backend.api.schemas import (
    AnalysisCreateRequest,
    AnalysisCreateResponse,
    AnalysisListResponse,
    AnalysisResponse,
    ErrorResponse,
)
from backend.api.sse import (
    event_payload,
    event_seq,
    event_type_of,
    format_live_model_sse_event,
    format_sse_event,
    is_terminal_stream_event,
    parse_last_event_id,
    should_emit_live_model_event,
)
from backend.api.services import AnalysisRecord, InMemoryAnalysisService, encode_list_cursor, maybe_await
from backend.api.stream_schemas import TERMINAL_ANALYSIS_STATUSES, status_event_payload
from backend.ids import new_uuid7


def get_analysis_service(request: Request) -> InMemoryAnalysisService:
    return request.app.state.analysis_service


def get_live_stream_hub(request: Request):
    return getattr(request.app.state, "live_stream_hub", None)


def get_show_model_reasoning_summary(request: Request) -> bool:
    return bool(getattr(request.app.state, "show_model_reasoning_summary", True))


router = APIRouter()


@router.post(
    "/analysis",
    response_model=AnalysisCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_analysis(
    body: AnalysisCreateRequest,
    service: InMemoryAnalysisService = Depends(get_analysis_service),
) -> AnalysisCreateResponse:
    record = await maybe_await(
        service.create(
            repository_url=str(body.repository_url),
            requested_ref=body.ref,
            analysis_profile_id=body.analysis_profile_id,
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
    status_filter: str | None = Query(default=None, alias="status"),
    repository_url_hash: str | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    service: InMemoryAnalysisService = Depends(get_analysis_service),
) -> AnalysisListResponse:
    records = await maybe_await(
        service.list(
            status=status_filter,
            repository_url_hash=repository_url_hash,
            created_after=created_after,
            created_before=created_before,
            limit=limit + 1,
            cursor=cursor,
        )
    )
    page = records[:limit]
    next_cursor = encode_list_cursor(page[-1]) if len(records) > limit and page else None
    return AnalysisListResponse(
        items=[_to_response(record) for record in page],
        next_cursor=next_cursor,
    )


@router.get(
    "/analysis/{analysis_id}",
    response_model=AnalysisResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_analysis(
    analysis_id: UUID,
    service: InMemoryAnalysisService = Depends(get_analysis_service),
) -> AnalysisResponse:
    record = await maybe_await(service.get(analysis_id))
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
    service: InMemoryAnalysisService = Depends(get_analysis_service),
) -> AnalysisResponse:
    record = await maybe_await(service.cancel(analysis_id))
    if record is None:
        raise _not_found()
    return _to_response(record)


@router.get(
    "/analysis/{analysis_id}/events",
    responses={404: {"model": ErrorResponse}},
)
async def stream_analysis_events(
    analysis_id: UUID,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    poll_interval_seconds: float = Query(default=0.2, ge=0, le=10),
    idle_timeout_seconds: float = Query(default=30.0, ge=0, le=300),
    debug_raw_llm_events: bool = Query(default=False),
    service: InMemoryAnalysisService = Depends(get_analysis_service),
    live_stream_hub=Depends(get_live_stream_hub),
    show_model_reasoning_summary: bool = Depends(get_show_model_reasoning_summary),
) -> StreamingResponse:
    record = await maybe_await(service.get(analysis_id))
    if record is None:
        raise _not_found()
    after_seq = parse_last_event_id(last_event_id)
    events_method = getattr(service, "stream_events", None)
    if events_method is not None:
        if getattr(service, "supports_live_events", False):
            return StreamingResponse(
                _live_sse_event_records(
                    service,
                    analysis_id,
                    after_seq=after_seq,
                    poll_interval_seconds=poll_interval_seconds,
                    idle_timeout_seconds=idle_timeout_seconds,
                    live_stream_hub=live_stream_hub,
                    debug_raw_llm_events=debug_raw_llm_events,
                    show_model_reasoning_summary=show_model_reasoning_summary,
                ),
                media_type="text/event-stream",
            )
        events = await maybe_await(events_method(analysis_id, after_seq=after_seq))
        return StreamingResponse(_sse_event_records(events), media_type="text/event-stream")
    return StreamingResponse(_sse_events(record, after_seq=after_seq), media_type="text/event-stream")


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


def _sse_events(record: AnalysisRecord, *, after_seq: int = 0) -> Iterator[str]:
    if after_seq >= 1:
        return
    payload = json.dumps(status_event_payload(status=record.status), separators=(",", ":"))
    yield f"id: 1\nevent: status\ndata: {payload}\n\n"


def _sse_event_records(events: Iterable) -> Iterator[str]:
    for event in events:
        yield _format_sse_event(event)


async def _live_sse_event_records(
    service: InMemoryAnalysisService,
    analysis_id: UUID,
    *,
    after_seq: int,
    poll_interval_seconds: float,
    idle_timeout_seconds: float,
    live_stream_hub=None,
    debug_raw_llm_events: bool = False,
    show_model_reasoning_summary: bool = True,
) -> AsyncIterator[str]:
    last_seq = after_seq
    loop = asyncio.get_running_loop()
    idle_deadline = loop.time() + idle_timeout_seconds
    status_method = getattr(service, "analysis_status", None)
    live_subscription = live_stream_hub.subscribe(analysis_id) if live_stream_hub is not None else None

    try:
        while True:
            if live_subscription is not None:
                try:
                    live_event = live_subscription.get_nowait()
                    if not should_emit_live_model_event(
                        live_event,
                        debug_raw_llm_events=debug_raw_llm_events,
                        show_model_reasoning_summary=show_model_reasoning_summary,
                    ):
                        continue
                    idle_deadline = loop.time() + idle_timeout_seconds
                    yield format_live_model_sse_event(live_event)
                    continue
                except asyncio.QueueEmpty:
                    pass

            events = await maybe_await(service.stream_events(analysis_id, after_seq=last_seq))
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

            if live_subscription is not None:
                timeout = 0 if poll_interval_seconds <= 0 else poll_interval_seconds
                try:
                    live_event = await asyncio.wait_for(live_subscription.get(), timeout=timeout)
                    if not should_emit_live_model_event(
                        live_event,
                        debug_raw_llm_events=debug_raw_llm_events,
                        show_model_reasoning_summary=show_model_reasoning_summary,
                    ):
                        continue
                    idle_deadline = loop.time() + idle_timeout_seconds
                    yield format_live_model_sse_event(live_event)
                    continue
                except asyncio.TimeoutError:
                    pass

            if status_method is not None:
                current_status = await maybe_await(status_method(analysis_id))
                if current_status in TERMINAL_ANALYSIS_STATUSES:
                    events = await maybe_await(service.stream_events(analysis_id, after_seq=last_seq))
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
            if live_subscription is None:
                if poll_interval_seconds > 0:
                    await asyncio.sleep(poll_interval_seconds)
                else:
                    await asyncio.sleep(0)
    finally:
        if live_subscription is not None:
            live_subscription.close()


def _format_sse_event(event) -> str:
    return format_sse_event(event)


def _event_seq(event) -> int:
    return event_seq(event)


def _event_type(event) -> str:
    return event_type_of(event)


def _event_payload(event) -> dict:
    return event_payload(event)


def _is_terminal_event(event) -> bool:
    return is_terminal_stream_event(event)


def _parse_last_event_id(value: str | None) -> int:
    return parse_last_event_id(value)


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
