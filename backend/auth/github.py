from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, cast

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"


@dataclass(frozen=True)
class GitHubOAuthConfig:
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    frontend_redirect_uri: str = ""
    state_ttl_seconds: int = 600
    exchange_code_ttl_seconds: int = 60
    allowed_email_domains: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str
    name: str | None


@dataclass(frozen=True)
class GitHubEmail:
    email: str
    primary: bool
    verified: bool


class GitHubOAuthClient(Protocol):
    async def exchange_code_for_token(self, *, code: str, redirect_uri: str) -> str: ...

    async def get_user(self, access_token: str) -> GitHubUser: ...

    async def list_emails(self, access_token: str) -> list[GitHubEmail]: ...


class UrlLibGitHubOAuthClient:
    def __init__(self, config: GitHubOAuthConfig) -> None:
        self._config = config

    async def exchange_code_for_token(self, *, code: str, redirect_uri: str) -> str:
        return await asyncio.to_thread(self.exchange_code_for_token_sync, code=code, redirect_uri=redirect_uri)

    async def get_user(self, access_token: str) -> GitHubUser:
        return await asyncio.to_thread(self.get_user_sync, access_token)

    async def list_emails(self, access_token: str) -> list[GitHubEmail]:
        return await asyncio.to_thread(self.list_emails_sync, access_token)

    def exchange_code_for_token_sync(self, *, code: str, redirect_uri: str) -> str:
        payload = {
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        data = _request_json(
            GITHUB_ACCESS_TOKEN_URL,
            method="POST",
            headers={"Accept": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
        )
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise GitHubOAuthError("GitHub did not return an access token.")
        return token

    def get_user_sync(self, access_token: str) -> GitHubUser:
        data = _request_json(f"{GITHUB_API_URL}/user", headers=_github_headers(access_token))
        user_id = data.get("id")
        login = data.get("login")
        if not isinstance(user_id, int) or not isinstance(login, str):
            raise GitHubOAuthError("GitHub user response is missing required fields.")
        name = data.get("name")
        return GitHubUser(id=user_id, login=login, name=name if isinstance(name, str) else None)

    def list_emails_sync(self, access_token: str) -> list[GitHubEmail]:
        data = _request_json(f"{GITHUB_API_URL}/user/emails", headers=_github_headers(access_token))
        if not isinstance(data, list):
            raise GitHubOAuthError("GitHub emails response is invalid.")
        emails: list[GitHubEmail] = []
        for item in cast(list[Any], data):
            if not isinstance(item, dict):
                continue
            email_data = cast(dict[str, Any], item)
            email = email_data.get("email")
            if isinstance(email, str):
                emails.append(
                    GitHubEmail(
                        email=email,
                        primary=bool(email_data.get("primary")),
                        verified=bool(email_data.get("verified")),
                    )
                )
        return emails


class GitHubOAuthError(ValueError):
    pass


def github_authorize_url(*, config: GitHubOAuthConfig, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{query}"


def primary_verified_email(emails: list[GitHubEmail]) -> str | None:
    for email in emails:
        if email.primary and email.verified:
            return email.email
    for email in emails:
        if email.verified:
            return email.email
    return None


def _github_headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> Any:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
