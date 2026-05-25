from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RepositorySuggestionQuery:
    repository_url: str | None
    repository_url_prefix: str | None


def normalize_repository_query(value: str) -> str | None:
    query = value.strip()
    if not query:
        return None
    if _is_github_shorthand(query):
        return f"https://github.com/{query}.git"

    parsed = urlsplit(query)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        return query
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path.removesuffix(".git")
    if path.count("/") != 1:
        return None
    return f"https://github.com/{path}.git"


def parse_repository_suggestion_query(value: str) -> RepositorySuggestionQuery | None:
    query = value.strip()
    if not query:
        return None
    if _is_github_prefix_shorthand(query):
        return RepositorySuggestionQuery(
            repository_url=None,
            repository_url_prefix=f"https://github.com/{query}",
        )

    parsed = urlsplit(query)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "github.com":
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path.removesuffix(".git")
            if _is_github_shorthand(path):
                return RepositorySuggestionQuery(
                    repository_url=f"https://github.com/{path}.git",
                    repository_url_prefix=None,
                )
        elif _is_github_prefix_shorthand(path):
            return RepositorySuggestionQuery(
                repository_url=None,
                repository_url_prefix=f"https://github.com/{path}",
            )

    repository_url = normalize_repository_query(query)
    if repository_url is None:
        return None
    return RepositorySuggestionQuery(repository_url=repository_url, repository_url_prefix=None)


def _is_github_shorthand(value: str) -> bool:
    parts = value.split("/")
    if len(parts) != 2:
        return False
    return all(
        part and all(character.isalnum() or character in {"_", ".", "-"} for character in part) for part in parts
    )


def _is_github_prefix_shorthand(value: str) -> bool:
    parts = value.split("/")
    if len(parts) != 2:
        return False
    owner, repo_prefix = parts
    return _is_github_path_part(owner) and _is_github_path_prefix(repo_prefix)


def _is_github_path_part(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in {"_", ".", "-"} for character in value)


def _is_github_path_prefix(value: str) -> bool:
    return all(character.isalnum() or character in {"_", ".", "-"} for character in value)
