from __future__ import annotations

import unittest

from backend.api.app import create_app
from backend.document import DocumentService
from backend.ids import new_uuid7
from fastapi.testclient import TestClient


class DocumentApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_user_can_list_and_read_analysis_documents(self) -> None:
        app = create_app()
        client = TestClient(app)
        tokens = _register_and_login(client, "docs@example.com")
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        analysis = client.post(
            "/api/analysis",
            json={"repository_url": "https://github.com/example/project.git", "ref": "main"},
            headers=headers,
        ).json()

        document = await app.state.document_service.create(
            analysis_id=analysis["analysis_id"],
            agent_id=analysis["agent_id"],
            tool_call_id=new_uuid7(),
            title="Repository review",
            kind="markdown",
            content="# Review\n\nFindings.",
        )

        listed = client.get(f"/api/analysis/{analysis['analysis_id']}/documents", headers=headers)
        detail = client.get(
            f"/api/analysis/{analysis['analysis_id']}/documents/{document['document_id']}",
            headers=headers,
        )
        content = client.get(
            f"/api/analysis/{analysis['analysis_id']}/documents/{document['document_id']}/content",
            headers=headers,
        )
        revisions = client.get(
            f"/api/analysis/{analysis['analysis_id']}/documents/{document['document_id']}/revisions",
            headers=headers,
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["document_id"], document["document_id"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["title"], "Repository review")
        self.assertEqual(content.status_code, 200)
        self.assertEqual(content.json()["content"], "# Review\n\nFindings.")
        self.assertEqual(revisions.status_code, 200)
        self.assertEqual(revisions.json()["items"][0]["version"], 1)
        self.assertIsInstance(app.state.document_service, DocumentService)

    async def test_user_cannot_read_other_tenant_documents(self) -> None:
        app = create_app()
        client = TestClient(app)
        owner_tokens = _register_and_login(client, "owner@example.com")
        other_tokens = _register_and_login(client, "other@example.com")
        owner_headers = {"Authorization": f"Bearer {owner_tokens['access_token']}"}
        other_headers = {"Authorization": f"Bearer {other_tokens['access_token']}"}
        analysis = client.post(
            "/api/analysis",
            json={"repository_url": "https://github.com/example/private.git", "ref": "main"},
            headers=owner_headers,
        ).json()

        document = await app.state.document_service.create(
            analysis_id=analysis["analysis_id"],
            agent_id=analysis["agent_id"],
            tool_call_id=new_uuid7(),
            title="Private review",
            kind="markdown",
            content="secret",
        )

        response = client.get(
            f"/api/analysis/{analysis['analysis_id']}/documents/{document['document_id']}/content",
            headers=other_headers,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "ANALYSIS_NOT_FOUND")


def _register_and_login(client: TestClient, email: str) -> dict[str, object]:
    client.post("/api/auth/register", json={"email": email, "password": "correct horse battery staple"})
    return client.post("/api/auth/login", json={"email": email, "password": "correct horse battery staple"}).json()


if __name__ == "__main__":
    unittest.main()
