from __future__ import annotations

import unittest
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from backend.api.app import create_app
from backend.auth.github import GitHubEmail, GitHubOAuthConfig, GitHubUser
from backend.auth.oauth import (
    InMemoryOAuthCodeStore,
    InMemoryOAuthStateStore,
    RedisOAuthCodeStore,
    RedisOAuthStateStore,
)
from backend.auth.turnstile import TurnstileConfig, TurnstileVerification
from fastapi.testclient import TestClient


@dataclass
class RecordingTurnstileVerifier:
    verifications: list[TurnstileVerification]
    should_pass: bool = True

    async def verify(self, verification: TurnstileVerification) -> bool:
        self.verifications.append(verification)
        return self.should_pass


class FakeGitHubOAuthClient:
    def __init__(
        self,
        *,
        user: GitHubUser | None = None,
        emails: list[GitHubEmail] | None = None,
    ) -> None:
        self.exchanged_codes: list[str] = []
        self.user = user or GitHubUser(id=12345, login="octocat", name="The Octocat")
        self.emails = emails or [
            GitHubEmail(email="octocat@example.com", primary=True, verified=True),
        ]

    async def exchange_code_for_token(self, *, code: str, redirect_uri: str) -> str:
        del redirect_uri
        self.exchanged_codes.append(code)
        return "github-access-token"

    async def get_user(self, access_token: str) -> GitHubUser:
        self.assert_access_token(access_token)
        return self.user

    async def list_emails(self, access_token: str) -> list[GitHubEmail]:
        self.assert_access_token(access_token)
        return self.emails

    def assert_access_token(self, access_token: str) -> None:
        if access_token != "github-access-token":
            raise AssertionError(f"unexpected access token: {access_token}")


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setex(self, name: str, time: object, value: str) -> object:
        del time
        self.values[name] = value
        return True

    def getdel(self, name: str) -> str | bytes | None:
        return self.values.pop(name, None)


class AuthApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_register_login_me_and_refresh_token_flow(self) -> None:
        created = self.client.post(
            "/auth/register",
            json={"email": "alice@example.com", "password": "correct horse battery staple", "display_name": "Alice"},
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["email"], "alice@example.com")
        self.assertNotIn("password", created.text)

        logged_in = self.client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "correct horse battery staple"},
        )

        self.assertEqual(logged_in.status_code, 200)
        tokens = logged_in.json()
        self.assertEqual(tokens["token_type"], "bearer")
        self.assertIn("access_token", tokens)
        self.assertIn("refresh_token", tokens)

        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})

        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "alice@example.com")
        self.assertIn("analysis:create", me.json()["permissions"])

        refreshed = self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("access_token", refreshed.json())

        reused = self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assertEqual(reused.status_code, 401)
        self.assertEqual(reused.json()["error"]["code"], "INVALID_REFRESH_TOKEN")

    def test_analysis_requires_jwt(self) -> None:
        response = self.client.post(
            "/analysis",
            json={"repository_url": "https://github.com/example/project.git", "ref": "main"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "AUTH_REQUIRED")

    def test_registered_member_can_create_analysis_with_jwt(self) -> None:
        tokens = self._register_and_login("bob@example.com")

        response = self.client.post(
            "/analysis",
            json={"repository_url": "https://github.com/example/project.git", "ref": "main"},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "queued")

    def test_invalid_login_is_rejected(self) -> None:
        self.client.post(
            "/auth/register",
            json={"email": "eve@example.com", "password": "correct horse battery staple"},
        )

        response = self.client.post("/auth/login", json={"email": "eve@example.com", "password": "wrong"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "INVALID_CREDENTIALS")

    def test_turnstile_token_is_required_for_register_when_enabled(self) -> None:
        verifier = RecordingTurnstileVerifier(verifications=[])
        app = create_app()
        app.state.turnstile_config = TurnstileConfig(enabled=True, secret_key="secret")
        app.state.turnstile_verifier = verifier
        client = TestClient(app)

        response = client.post(
            "/auth/register",
            json={"email": "guarded@example.com", "password": "correct horse battery staple"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "TURNSTILE_REQUIRED")
        self.assertEqual(verifier.verifications, [])

    def test_register_and_login_validate_turnstile_actions_when_enabled(self) -> None:
        verifier = RecordingTurnstileVerifier(verifications=[])
        app = create_app()
        app.state.turnstile_config = TurnstileConfig(enabled=True, secret_key="secret")
        app.state.turnstile_verifier = verifier
        client = TestClient(app)

        created = client.post(
            "/auth/register",
            json={
                "email": "guarded@example.com",
                "password": "correct horse battery staple",
                "turnstile_token": "register-token",
            },
        )
        logged_in = client.post(
            "/auth/login",
            json={
                "email": "guarded@example.com",
                "password": "correct horse battery staple",
                "turnstile_token": "login-token",
            },
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual([verification.action for verification in verifier.verifications], ["register", "login"])
        self.assertEqual(
            [verification.token for verification in verifier.verifications], ["register-token", "login-token"]
        )

    def test_turnstile_failure_rejects_login_before_password_check(self) -> None:
        verifier = RecordingTurnstileVerifier(verifications=[], should_pass=False)
        app = create_app()
        app.state.turnstile_config = TurnstileConfig(enabled=True, secret_key="secret")
        app.state.turnstile_verifier = verifier
        client = TestClient(app)

        response = client.post(
            "/auth/login",
            json={
                "email": "missing@example.com",
                "password": "wrong",
                "turnstile_token": "bad-token",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "TURNSTILE_FAILED")
        self.assertEqual(len(verifier.verifications), 1)

    def test_github_oauth_callback_creates_user_and_exchanges_internal_code_for_tokens(self) -> None:
        app = create_app()
        app.state.github_oauth_config = GitHubOAuthConfig(
            enabled=True,
            client_id="github-client-id",
            client_secret="github-client-secret",
            redirect_uri="http://testserver/auth/github/callback",
            frontend_redirect_uri="http://frontend.local/auth/callback",
        )
        app.state.github_oauth_client = FakeGitHubOAuthClient()
        app.state.oauth_state_store = InMemoryOAuthStateStore()
        app.state.oauth_code_store = InMemoryOAuthCodeStore()
        client = TestClient(app)

        start = client.get("/auth/github/start?redirect_to=/analysis", follow_redirects=False)
        self.assertEqual(start.status_code, 307)
        start_location = start.headers["location"]
        github_query = parse_qs(urlparse(start_location).query)
        self.assertEqual(github_query["client_id"], ["github-client-id"])
        self.assertEqual(github_query["scope"], ["read:user user:email"])

        callback = client.get(
            f"/auth/github/callback?code=github-code&state={github_query['state'][0]}",
            follow_redirects=False,
        )
        self.assertEqual(callback.status_code, 307)
        callback_location = callback.headers["location"]
        callback_query = parse_qs(urlparse(callback_location).query)
        self.assertEqual(urlparse(callback_location).scheme, "http")
        self.assertEqual(urlparse(callback_location).netloc, "frontend.local")
        self.assertEqual(callback_query["redirect_to"], ["/analysis"])

        exchanged = client.post("/auth/exchange", json={"code": callback_query["code"][0]})
        self.assertEqual(exchanged.status_code, 200)
        self.assertIn("access_token", exchanged.json())

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {exchanged.json()['access_token']}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "octocat@example.com")
        self.assertIn("admin", {role["name"] for role in me.json()["roles"]})

    def test_github_oauth_rejects_unverified_email(self) -> None:
        app = create_app()
        app.state.github_oauth_config = GitHubOAuthConfig(
            enabled=True,
            client_id="github-client-id",
            client_secret="github-client-secret",
            redirect_uri="http://testserver/auth/github/callback",
            frontend_redirect_uri="http://frontend.local/auth/callback",
        )
        app.state.github_oauth_client = FakeGitHubOAuthClient(
            emails=[GitHubEmail(email="octocat@example.com", primary=True, verified=False)]
        )
        app.state.oauth_state_store = InMemoryOAuthStateStore()
        app.state.oauth_code_store = InMemoryOAuthCodeStore()
        client = TestClient(app)

        start = client.get("/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        callback = client.get(f"/auth/github/callback?code=github-code&state={state}", follow_redirects=False)

        self.assertEqual(callback.status_code, 400)
        self.assertEqual(callback.json()["error"]["code"], "GITHUB_EMAIL_REQUIRED")

    def test_github_oauth_state_can_only_be_used_once(self) -> None:
        app = create_app()
        app.state.github_oauth_config = GitHubOAuthConfig(
            enabled=True,
            client_id="github-client-id",
            client_secret="github-client-secret",
            redirect_uri="http://testserver/auth/github/callback",
            frontend_redirect_uri="http://frontend.local/auth/callback",
        )
        app.state.github_oauth_client = FakeGitHubOAuthClient()
        app.state.oauth_state_store = InMemoryOAuthStateStore()
        app.state.oauth_code_store = InMemoryOAuthCodeStore()
        client = TestClient(app)

        start = client.get("/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        first = client.get(f"/auth/github/callback?code=github-code&state={state}", follow_redirects=False)
        second = client.get(f"/auth/github/callback?code=github-code&state={state}", follow_redirects=False)

        self.assertEqual(first.status_code, 307)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["error"]["code"], "INVALID_OAUTH_STATE")

    def test_password_login_for_oauth_only_user_is_rejected(self) -> None:
        app = create_app()
        app.state.github_oauth_config = GitHubOAuthConfig(
            enabled=True,
            client_id="github-client-id",
            client_secret="github-client-secret",
            redirect_uri="http://testserver/auth/github/callback",
            frontend_redirect_uri="http://frontend.local/auth/callback",
        )
        app.state.github_oauth_client = FakeGitHubOAuthClient()
        app.state.oauth_state_store = InMemoryOAuthStateStore()
        app.state.oauth_code_store = InMemoryOAuthCodeStore()
        client = TestClient(app)
        start = client.get("/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        client.get(f"/auth/github/callback?code=github-code&state={state}", follow_redirects=False)

        response = client.post(
            "/auth/login",
            json={"email": "octocat@example.com", "password": "wrong"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "INVALID_CREDENTIALS")

    def test_redis_oauth_stores_round_trip_and_consume_values_once(self) -> None:
        redis = FakeRedisClient()
        state_store = RedisOAuthStateStore(redis)
        code_store = RedisOAuthCodeStore(redis)

        state = state_store.create(redirect_to="/analysis", ttl_seconds=600)
        code = code_store.create(user_id="019e0000-0000-7000-8000-000000000001", ttl_seconds=60)

        self.assertEqual(state_store.pop(state).redirect_to, "/analysis")
        self.assertIsNone(state_store.pop(state))
        self.assertEqual(code_store.pop(code).user_id, "019e0000-0000-7000-8000-000000000001")
        self.assertIsNone(code_store.pop(code))

    def test_disabled_user_cannot_use_existing_access_token(self) -> None:
        admin_tokens = self._register_and_login("admin@example.com")
        created = self.client.post(
            "/users",
            json={"email": "inactive@example.com", "password": "correct horse battery staple"},
            headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
        )
        member_tokens = self.client.post(
            "/auth/login",
            json={"email": "inactive@example.com", "password": "correct horse battery staple"},
        ).json()

        self.client.patch(
            f"/users/{created.json()['id']}",
            json={"is_active": False},
            headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
        )

        response = self.client.get("/auth/me", headers={"Authorization": f"Bearer {member_tokens['access_token']}"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "INVALID_TOKEN")

    def _register_and_login(self, email: str) -> dict[str, object]:
        self.client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
        return self.client.post("/auth/login", json={"email": email, "password": "correct horse battery staple"}).json()


if __name__ == "__main__":
    unittest.main()
