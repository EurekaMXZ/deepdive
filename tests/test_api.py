from __future__ import annotations

import unittest
import uuid

from backend.api.app import create_app
from fastapi.testclient import TestClient


class AnalysisApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_create_analysis_returns_queued_resource(self) -> None:
        response = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/project.git",
                "ref": "main",
            },
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(uuid.UUID(body["analysis_id"]).version, 7)
        self.assertEqual(uuid.UUID(body["agent_id"]).version, 7)
        self.assertIsNone(body["snapshot_id"])
        self.assertEqual(body["status"], "queued")
        self.assertIn("created_at", body)

    def test_create_analysis_rejects_repository_url_credentials(self) -> None:
        response = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://token123@github.com/example/private.git",
                "ref": "main",
            },
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
        ).json()

        listed = self.client.get("/analysis")
        detail = self.client.get(f"/analysis/{created['analysis_id']}")

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
        ).json()
        second = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/second.git",
                "ref": "main",
            },
        ).json()

        page_one = self.client.get("/analysis", params={"limit": 1})
        page_two = self.client.get("/analysis", params={"limit": 1, "cursor": page_one.json()["next_cursor"]})

        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_two.status_code, 200)
        self.assertEqual([item["analysis_id"] for item in page_one.json()["items"]], [second["analysis_id"]])
        self.assertEqual([item["analysis_id"] for item in page_two.json()["items"]], [first["analysis_id"]])
        self.assertIsNone(page_two.json()["next_cursor"])

    def test_cancel_analysis_moves_status_to_cancelling(self) -> None:
        created = self.client.post(
            "/analysis",
            json={
                "repository_url": "https://github.com/example/project.git",
                "ref": "main",
            },
        ).json()

        response = self.client.post(f"/analysis/{created['analysis_id']}/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelling")

    def test_unknown_analysis_returns_standard_error(self) -> None:
        missing_id = "019e505e-df2b-7e6f-9a5e-141aa98f59da"

        response = self.client.get(f"/analysis/{missing_id}")

        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body["error"]["code"], "ANALYSIS_NOT_FOUND")
        self.assertEqual(uuid.UUID(body["error"]["request_id"]).version, 7)


if __name__ == "__main__":
    unittest.main()
