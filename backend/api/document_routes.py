from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from backend.api.auth_dependencies import require_permission
from backend.api.pagination import cursor_offset
from backend.api.routes import AnalysisService, get_analysis_service
from backend.api.services import maybe_await
from backend.auth import CurrentUser
from backend.document import DocumentToolError
from backend.ids import new_uuid7


class DocumentQueryService(Protocol):
    async def list(self, *, analysis_id: UUID, limit: int = 50, cursor: str | None = None) -> list[dict[str, Any]]: ...

    async def get(self, *, analysis_id: UUID, document_id: UUID, include_content: bool) -> dict[str, Any]: ...

    async def tree(self, *, analysis_id: UUID) -> list[dict[str, Any]]: ...

    async def list_revisions(
        self, *, analysis_id: UUID, document_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> list[dict[str, Any]]: ...


class DocumentResponse(BaseModel):
    document_id: UUID
    analysis_id: UUID
    agent_id: UUID
    title: str
    kind: str
    status: str
    version: int
    content_ref: str
    content_hash: str
    size_bytes: int
    focus_area: str | None = None
    node: dict[str, Any] | None = None
    sections: list[dict[str, Any]] | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    next_cursor: str | None = None


class DocumentTreeNodeResponse(BaseModel):
    node_id: UUID
    node_type: str
    document_id: UUID | None = None
    title: str
    slug: str
    path: str
    focus_area: str | None = None
    sort_order: int
    status: str | None = None
    version: int | None = None
    section_count: int
    children: list[DocumentTreeNodeResponse]


class DocumentTreeResponse(BaseModel):
    items: list[DocumentTreeNodeResponse]


class DocumentContentResponse(DocumentResponse):
    content: str


class DocumentRevisionResponse(BaseModel):
    revision_id: UUID
    document_id: UUID
    version: int
    tool_call_id: UUID
    operation: str
    content_ref: str
    content_hash: str
    size_bytes: int
    created_at: datetime


class DocumentRevisionListResponse(BaseModel):
    items: list[DocumentRevisionResponse]
    next_cursor: str | None = None


router = APIRouter(tags=["documents"])


def get_document_service(request: Request) -> DocumentQueryService:
    return request.app.state.document_service


@router.get("/analysis/{analysis_id}/documents", response_model=DocumentListResponse)
async def list_analysis_documents(
    analysis_id: UUID,
    analysis_service: Annotated[AnalysisService, Depends(get_analysis_service)],
    document_service: Annotated[DocumentQueryService, Depends(get_document_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("documents:read"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> DocumentListResponse:
    await _ensure_analysis_readable(analysis_service, analysis_id, current_user)
    offset = cursor_offset(cursor)
    documents = await document_service.list(analysis_id=analysis_id, limit=limit + 1, cursor=cursor)
    page = documents[:limit]
    next_cursor = str(offset + limit) if len(documents) > limit else None
    return DocumentListResponse(items=[DocumentResponse(**document) for document in page], next_cursor=next_cursor)


@router.get("/analysis/{analysis_id}/documents/tree", response_model=DocumentTreeResponse)
async def get_analysis_documents_tree(
    analysis_id: UUID,
    analysis_service: Annotated[AnalysisService, Depends(get_analysis_service)],
    document_service: Annotated[DocumentQueryService, Depends(get_document_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("documents:read"))],
) -> DocumentTreeResponse:
    await _ensure_analysis_readable(analysis_service, analysis_id, current_user)
    items = await document_service.tree(analysis_id=analysis_id)
    return DocumentTreeResponse(items=[DocumentTreeNodeResponse(**item) for item in items])


@router.get("/analysis/{analysis_id}/documents/{document_id}", response_model=DocumentResponse)
async def get_analysis_document(
    analysis_id: UUID,
    document_id: UUID,
    analysis_service: Annotated[AnalysisService, Depends(get_analysis_service)],
    document_service: Annotated[DocumentQueryService, Depends(get_document_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("documents:read"))],
) -> DocumentResponse:
    await _ensure_analysis_readable(analysis_service, analysis_id, current_user)
    document = await _get_document(
        document_service, analysis_id=analysis_id, document_id=document_id, include_content=False
    )
    return DocumentResponse(**document)


@router.get("/analysis/{analysis_id}/documents/{document_id}/content", response_model=DocumentContentResponse)
async def get_analysis_document_content(
    analysis_id: UUID,
    document_id: UUID,
    analysis_service: Annotated[AnalysisService, Depends(get_analysis_service)],
    document_service: Annotated[DocumentQueryService, Depends(get_document_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("documents:read"))],
) -> DocumentContentResponse:
    await _ensure_analysis_readable(analysis_service, analysis_id, current_user)
    document = await _get_document(
        document_service, analysis_id=analysis_id, document_id=document_id, include_content=True
    )
    return DocumentContentResponse(**document)


@router.get("/analysis/{analysis_id}/documents/{document_id}/revisions", response_model=DocumentRevisionListResponse)
async def list_analysis_document_revisions(
    analysis_id: UUID,
    document_id: UUID,
    analysis_service: Annotated[AnalysisService, Depends(get_analysis_service)],
    document_service: Annotated[DocumentQueryService, Depends(get_document_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("documents:read"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> DocumentRevisionListResponse:
    await _ensure_analysis_readable(analysis_service, analysis_id, current_user)
    try:
        offset = cursor_offset(cursor)
        revisions = await document_service.list_revisions(
            analysis_id=analysis_id, document_id=document_id, limit=limit + 1, cursor=cursor
        )
    except DocumentToolError as exc:
        raise _document_exception(exc.code, exc.message, status.HTTP_404_NOT_FOUND) from exc
    page = revisions[:limit]
    next_cursor = str(offset + limit) if len(revisions) > limit else None
    return DocumentRevisionListResponse(
        items=[DocumentRevisionResponse(**revision) for revision in page], next_cursor=next_cursor
    )


async def _ensure_analysis_readable(
    service: AnalysisService,
    analysis_id: UUID,
    current_user: CurrentUser,
) -> None:
    record = await maybe_await(
        service.get(analysis_id, tenant_id=current_user.tenant_id, created_by_user_id=current_user.id)
    )
    if record is None:
        raise _document_exception("ANALYSIS_NOT_FOUND", "Analysis does not exist.", status.HTTP_404_NOT_FOUND)


async def _get_document(
    service: DocumentQueryService,
    *,
    analysis_id: UUID,
    document_id: UUID,
    include_content: bool,
) -> dict[str, Any]:
    try:
        return await service.get(analysis_id=analysis_id, document_id=document_id, include_content=include_content)
    except DocumentToolError as exc:
        raise _document_exception(exc.code, exc.message, status.HTTP_404_NOT_FOUND) from exc
    except KeyError as exc:
        raise _document_exception(
            "DOCUMENT_CONTENT_NOT_FOUND", "Document content object was not found.", status.HTTP_404_NOT_FOUND
        ) from exc
    except UnicodeDecodeError as exc:
        raise _document_exception(
            "DOCUMENT_CONTENT_INVALID", "Document content is not valid UTF-8.", status.HTTP_500_INTERNAL_SERVER_ERROR
        ) from exc


def _document_exception(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "request_id": str(new_uuid7()),
            }
        },
    )
