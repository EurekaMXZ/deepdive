from __future__ import annotations

from backend.document.memory_repository import DocumentRepository
from backend.document.postgres_repository import PostgresDocumentRepository

__all__ = ["DocumentRepository", "PostgresDocumentRepository"]
