from __future__ import annotations

from uuid import UUID


def git_bundle_key(repository_url_hash: str, commit_sha: str) -> str:
    return f"git-bundles/{_hash_value(repository_url_hash)}/{commit_sha}.bundle"


def manifest_key(snapshot_id: UUID) -> str:
    return f"snapshots/{snapshot_id}/manifest.json.zst"


def tree_text_key(snapshot_id: UUID) -> str:
    return f"snapshots/{snapshot_id}/tree.txt"


def file_tree_key(snapshot_id: UUID) -> str:
    return f"snapshots/{snapshot_id}/file-tree.json.zst"


def blob_key(content_hash: str) -> str:
    digest = _hash_value(content_hash)
    return f"blobs/sha256/{digest[:2]}/{digest[2:4]}/{digest}"


def instruction_key(snapshot_id: UUID, path_hash: str) -> str:
    return f"instructions/{snapshot_id}/{_hash_value(path_hash)}.md"


def tool_result_key(tool_call_id: UUID) -> str:
    return f"tool-results/{tool_call_id}.json"


def evidence_key(evidence_id: UUID) -> str:
    return f"evidence/{evidence_id}.txt"


def document_content_key(analysis_id: UUID, document_id: UUID, version: int, tool_call_id: UUID | None = None) -> str:
    revision_suffix = f"-{tool_call_id}" if tool_call_id is not None else ""
    return f"documents/{analysis_id}/{document_id}/v{version}{revision_suffix}.md"


def document_section_content_key(
    analysis_id: UUID,
    document_id: UUID,
    section_id: UUID,
    version: int,
    tool_call_id: UUID | None = None,
) -> str:
    revision_suffix = f"-{tool_call_id}" if tool_call_id is not None else ""
    return f"documents/{analysis_id}/{document_id}/sections/{section_id}/v{version}{revision_suffix}.md"


def _hash_value(value: str) -> str:
    return value.split(":", 1)[1] if ":" in value else value
