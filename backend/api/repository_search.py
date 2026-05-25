from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.api.records import AnalysisRecord, RepositorySearchRecord


@dataclass(frozen=True)
class CanonicalRepository:
    repository_url: str
    repository_host: str
    repository_owner: str | None
    repository_name: str | None
    repository_label: str
    search_text: str


@dataclass
class RepositoryIndexEntry:
    canonical: CanonicalRepository
    latest_analysis: AnalysisRecord
    analysis_count: int
    completed_analysis_count: int


def canonicalize_repository_url(repository_url: str) -> CanonicalRepository:
    parsed = urlsplit(repository_url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path.removesuffix(".git")

    if host == "github.com" and _is_github_repo_path(path):
        owner, name = path.split("/", 1)
        label = f"{owner}/{name}"
        canonical_url = f"https://github.com/{label}.git"
        search_text = " ".join(
            item
            for item in [
                label,
                owner,
                name,
                name.replace("-", " "),
                name.replace(".", " "),
                "github.com",
                canonical_url,
            ]
            if item
        )
        return CanonicalRepository(
            repository_url=canonical_url,
            repository_host="github.com",
            repository_owner=owner,
            repository_name=name,
            repository_label=label,
            search_text=search_text.lower(),
        )

    label = repository_url.strip()
    search_text = " ".join(item for item in [label, host, path.replace("/", " ")] if item)
    return CanonicalRepository(
        repository_url=label,
        repository_host=host,
        repository_owner=None,
        repository_name=None,
        repository_label=label,
        search_text=search_text.lower(),
    )


def repository_search_score(record: RepositorySearchRecord, query: str) -> float:
    normalized_query = normalize_repository_search_query(query)
    if not normalized_query:
        return 1.0
    label = record.repository_label.lower()
    name = label.rsplit("/", 1)[-1]
    search_text = " ".join([label, record.repository_url.lower()])
    if label == normalized_query:
        return 100.0
    if label.startswith(normalized_query):
        return 90.0
    if name == normalized_query:
        return 85.0
    if name.startswith(normalized_query):
        return 80.0
    if normalized_query in search_text:
        return 70.0
    tokens = [token for token in normalized_query.replace("/", " ").split() if token]
    if tokens and all(token in search_text for token in tokens):
        return 60.0
    return 0.0


def repository_record_from_entry(entry: RepositoryIndexEntry) -> RepositorySearchRecord:
    latest = entry.latest_analysis
    return RepositorySearchRecord(
        repository_url=entry.canonical.repository_url,
        repository_label=entry.canonical.repository_label,
        latest_analysis_id=latest.analysis_id,
        latest_status=latest.status,
        latest_requested_ref=latest.requested_ref,
        latest_resolved_commit_sha=latest.resolved_commit_sha,
        analysis_count=entry.analysis_count,
        completed_analysis_count=entry.completed_analysis_count,
        last_analyzed_at=latest.updated_at,
    )


def normalize_repository_search_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _is_github_repo_path(path: str) -> bool:
    parts = path.split("/")
    if len(parts) != 2:
        return False
    return all(part and all(character.isalnum() or character in {"_", ".", "-"} for character in part) for part in parts)
