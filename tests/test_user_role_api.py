from __future__ import annotations

import unittest

from backend.api.app import create_app
from fastapi.testclient import TestClient


class UserRoleApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())
        self.admin_tokens = self._register_and_login("admin@example.com")

    def test_admin_can_create_list_update_disable_users(self) -> None:
        created = self.client.post(
            "/api/users",
            json={"email": "member@example.com", "password": "correct horse battery staple", "display_name": "Member"},
            headers=self._auth(),
        )

        self.assertEqual(created.status_code, 201)
        user_id = created.json()["id"]

        listed = self.client.get("/api/users", headers=self._auth())
        self.assertEqual(listed.status_code, 200)
        self.assertIn("member@example.com", {item["email"] for item in listed.json()["items"]})

        updated = self.client.patch(
            f"/api/users/{user_id}",
            json={"display_name": "Renamed", "is_active": False},
            headers=self._auth(),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["display_name"], "Renamed")
        self.assertFalse(updated.json()["is_active"])

    def test_admin_can_assign_roles_and_permissions(self) -> None:
        created = self.client.post(
            "/api/users",
            json={"email": "viewer@example.com", "password": "correct horse battery staple"},
            headers=self._auth(),
        )
        user_id = created.json()["id"]

        roles = self.client.get("/api/roles", headers=self._auth())
        self.assertEqual(roles.status_code, 200)
        viewer_role_id = next(role["id"] for role in roles.json()["items"] if role["name"] == "viewer")

        assigned = self.client.put(f"/api/users/{user_id}/roles", json={"role_ids": [viewer_role_id]}, headers=self._auth())
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual([role["name"] for role in assigned.json()["roles"]], ["viewer"])

        permissions = self.client.get("/api/permissions", headers=self._auth())
        self.assertEqual(permissions.status_code, 200)
        self.assertIn("analysis:read", {permission["name"] for permission in permissions.json()["items"]})

    def test_assigning_unknown_role_is_rejected(self) -> None:
        created = self.client.post(
            "/api/users",
            json={"email": "unknown-role@example.com", "password": "correct horse battery staple"},
            headers=self._auth(),
        )

        response = self.client.put(
            f"/api/users/{created.json()['id']}/roles",
            json={"role_ids": ["019e505e-df2b-7e6f-9a5e-141aa98f59da"]},
            headers=self._auth(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "ROLE_NOT_FOUND")

    def test_member_cannot_manage_users(self) -> None:
        member_tokens = self._register_and_login("member2@example.com")

        response = self.client.get("/api/users", headers={"Authorization": f"Bearer {member_tokens['access_token']}"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "FORBIDDEN")

    def _register_and_login(self, email: str) -> dict[str, object]:
        self.client.post("/api/auth/register", json={"email": email, "password": "correct horse battery staple"})
        return self.client.post("/api/auth/login", json={"email": email, "password": "correct horse battery staple"}).json()

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.admin_tokens['access_token']}"}


if __name__ == "__main__":
    unittest.main()
