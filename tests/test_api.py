from __future__ import annotations

import unittest
import uuid

from backend.api.app import create_app
from backend.auth.turnstile import TurnstileConfig
from fastapi.testclient import TestClient


class AnalysisApiTest(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.state.turnstile_config = TurnstileConfig(enabled=False)
        self.client = TestClient(app)
        self.headers = self._auth_headers()

    def test_create_analysis_returns_queued_resource(self) -> None:
        response = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/project.git",
                "ref": "main",
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(uuid.UUID(body["analysis_id"]).version, 7)
        self.assertEqual(uuid.UUID(body["agent_id"]).version, 7)
        self.assertIsNone(body["snapshot_id"])
        self.assertEqual(body["status"], "queued")
        self.assertIn("created_at", body)

    def test_create_analysis_batch_returns_pending_items(self) -> None:
        response = self.client.post(
            "/analysis/batches",
            json={
                "max_parallel": 2,
                "items": [
                    {
                        "repository_url": "https://github.com/example/one.git",
                        "ref": "main",
                    },
                    {
                        "repository_url": "https://github.com/example/two.git",
                        "ref": "release",
                    },
                    {
                        "repository_url": "https://github.com/example/three.git",
                        "ref": "main",
                    },
                ],
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(uuid.UUID(body["batch_id"]).version, 7)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["max_parallel"], 2)
        self.assertEqual(body["total_count"], 3)
        self.assertEqual(body["pending_count"], 3)
        self.assertEqual(body["active_count"], 0)
        self.assertEqual([item["status"] for item in body["items"]], ["pending", "pending", "pending"])
        self.assertEqual([item["sort_order"] for item in body["items"]], [0, 1, 2])
        self.assertEqual(body["items"][1]["requested_ref"], "release")

    def test_create_analysis_batch_rejects_repository_url_credentials(self) -> None:
        response = self.client.post(
            "/analysis/batches",
            json={
                "max_parallel": 2,
                "items": [
                    {
                        "repository_url": "https://token123@github.com/example/private.git",
                        "ref": "main",
                    }
                ],
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("repository_url", str(response.json()))

    def test_create_analysis_rejects_repository_url_credentials(self) -> None:
        response = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://token123@github.com/example/private.git",
                "ref": "main",
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("repository_url", str(response.json()))

    def test_create_analysis_rejects_repository_url_query_and_fragment(self) -> None:
        for repository_url in (
            "https://github.com/example/private.git?token=secret",
            "https://github.com/example/private.git#access_token=secret",
        ):
            with self.subTest(repository_url=repository_url):
                response = self.client.post(
                    "/analysis",
                    json={
                        "repository_url": repository_url,
                        "ref": "main",
                    },
                    headers=self.headers,
                )

                self.assertEqual(response.status_code, 422)
                self.assertIn("repository_url", str(response.json()))

    def test_create_analysis_rejects_unregistered_profile_id(self) -> None:
        response = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/project.git",
                "ref": "main",
                "analysis_profile_id": "019e505e-df2b-7e6f-9a5e-141aa98f59da",
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("analysis_profile_id", str(response.json()))

    def test_created_analysis_can_be_listed_and_read(self) -> None:
        created = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/project.git",
                "ref": "main",
            },
            headers=self.headers,
        ).json()

        listed = self.client.get("/analysis", headers=self.headers)
        detail = self.client.get(f"/analysis/{created['analysis_id']}", headers=self.headers)

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["analysis_id"], created["analysis_id"])
        self.assertIsNone(listed.json()["next_cursor"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["analysis_id"], created["analysis_id"])
        self.assertIn("error_code", detail.json())
        self.assertIn("error_message", detail.json())

    def test_analysis_list_supports_cursor_pagination(self) -> None:
        first = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/first.git",
                "ref": "main",
            },
            headers=self.headers,
        ).json()
        second = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/second.git",
                "ref": "main",
            },
            headers=self.headers,
        ).json()

        page_one = self.client.get("/analysis", params={"limit": 1}, headers=self.headers)
        page_two = self.client.get(
            "/analysis",
            params={"limit": 1, "cursor": page_one.json()["next_cursor"]},
            headers=self.headers,
        )

        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_two.status_code, 200)
        self.assertEqual([item["analysis_id"] for item in page_one.json()["items"]], [second["analysis_id"]])
        self.assertEqual([item["analysis_id"] for item in page_two.json()["items"]], [first["analysis_id"]])
        self.assertIsNone(page_two.json()["next_cursor"])

    def test_analysis_suggestions_return_recent_matching_repository_without_full_list(self) -> None:
        matching = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/openai/codex.git",
                "ref": "main",
            },
            headers=self.headers,
        ).json()
        self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/other.git",
                "ref": "main",
            },
            headers=self.headers,
        )

        response = self.client.get(
            "/analysis/suggestions",
            params={"repository_query": "openai/codex", "limit": 6},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["analysis_id"], matching["analysis_id"])
        self.assertEqual(body["items"][0]["repository_label"], "openai/codex")
        self.assertEqual(body["items"][0]["repository_url"], "https://github.com/openai/codex.git")

    def test_analysis_suggestions_support_repository_prefix_queries(self) -> None:
        matching = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/openai/codex.git",
                "ref": "main",
            },
            headers=self.headers,
        ).json()
        self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/vercel/next.js.git",
                "ref": "main",
            },
            headers=self.headers,
        )

        response = self.client.get(
            "/analysis/suggestions",
            params={"repository_query": "openai/co", "limit": 6},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["analysis_id"] for item in body["items"]], [matching["analysis_id"]])
        self.assertEqual(body["items"][0]["repository_label"], "openai/codex")

    def test_repository_search_returns_deduplicated_non_prefix_matches(self) -> None:
        older = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/openai/codex.git",
                "ref": "main",
            },
            headers=self.headers,
        ).json()
        latest = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/openai/codex.git",
                "ref": "release",
            },
            headers=self.headers,
        ).json()
        self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/vercel/next.js.git",
                "ref": "main",
            },
            headers=self.headers,
        )

        response = self.client.get(
            "/repositories/search",
            params={"q": "codex", "limit": 8},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["repository_label"], "openai/codex")
        self.assertEqual(body["items"][0]["repository_url"], "https://github.com/openai/codex.git")
        self.assertEqual(body["items"][0]["latest_analysis_id"], latest["analysis_id"])
        self.assertEqual(body["items"][0]["latest_requested_ref"], "release")
        self.assertEqual(body["items"][0]["analysis_count"], 2)
        self.assertEqual(body["items"][0]["completed_analysis_count"], 0)
        self.assertNotEqual(body["items"][0]["latest_analysis_id"], older["analysis_id"])

    def test_repository_search_is_scoped_to_current_user(self) -> None:
        self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/openai/codex.git",
                "ref": "main",
            },
            headers=self.headers,
        )
        other_headers = self._auth_headers("other-analysis@example.com")

        response = self.client.get(
            "/repositories/search",
            params={"q": "codex", "limit": 8},
            headers=other_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])

    def test_cancel_analysis_moves_status_to_cancelling(self) -> None:
        created = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/project.git",
                "ref": "main",
            },
            headers=self.headers,
        ).json()

        response = self.client.post(f"/analysis/{created['analysis_id']}/cancel", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelling")

    def test_unknown_analysis_returns_standard_error(self) -> None:
        missing_id = "019e505e-df2b-7e6f-9a5e-141aa98f59da"

        response = self.client.get(f"/analysis/{missing_id}", headers=self.headers)

        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body["error"]["code"], "ANALYSIS_NOT_FOUND")
        self.assertEqual(uuid.UUID(body["error"]["request_id"]).version, 7)

    def _auth_headers(self, email: str = "analysis@example.com") -> dict[str, str]:
        self.client.post(
            "/auth/register",
            json={"email": email, "password": "correct horse battery staple"},
        )
        tokens = self.client.post(
            "/auth/login",
            json={"email": email, "password": "correct horse battery staple"},
        ).json()
        return {"Authorization": f"Bearer {tokens['access_token']}"}


if __name__ == "__main__":
    unittest.main()
