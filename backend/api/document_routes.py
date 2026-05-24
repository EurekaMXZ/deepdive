from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.api.auth_dependencies import require_permission
from backend.api.routes import AnalysisService, get_analysis_service
from backend.api.services import maybe_await
from backend.auth import CurrentUser
from backend.document import DocumentToolError
from backend.ids import new_uuid7


class DocumentQueryService(Protocol):
    async def list(self, *, analysis_id: UUID) -> list[dict[str, Any]]: ...

    async def get(self, *, analysis_id: UUID, document_id: UUID, include_content: bool) -> dict[str, Any]: ...

    async def list_revisions(self, *, analysis_id: UUID, document_id: UUID) -> list[dict[str, Any]]: ...


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


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]


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


router = APIRouter(tags=["documents"])


def get_document_service(request: Request) -> DocumentQueryService:
    return request.app.state.document_service


@router.get("/analysis/{analysis_id}/documents", response_model=DocumentListResponse)
async def list_analysis_documents(
    analysis_id: UUID,
    analysis_service: Annotated[AnalysisService, Depends(get_analysis_service)],
    document_service: Annotated[DocumentQueryService, Depends(get_document_service)],
    current_user: Annotated[CurrentUser, Depends(require_permission("documents:read"))],
) -> DocumentListResponse:
    await _ensure_analysis_readable(analysis_service, analysis_id, current_user)
    documents = await document_service.list(analysis_id=analysis_id)
    return DocumentListResponse(items=[DocumentResponse(**document) for document in documents])


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
) -> DocumentRevisionListResponse:
    await _ensure_analysis_readable(analysis_service, analysis_id, current_user)
    try:
        revisions = await document_service.list_revisions(analysis_id=analysis_id, document_id=document_id)
    except DocumentToolError as exc:
        raise _document_exception(exc.code, exc.message, status.HTTP_404_NOT_FOUND) from exc
    return DocumentRevisionListResponse(items=[DocumentRevisionResponse(**revision) for revision in revisions])


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
