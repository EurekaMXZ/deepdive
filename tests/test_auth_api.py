from __future__ import annotations

import unittest

from backend.api.app import create_app
from fastapi.testclient import TestClient


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
