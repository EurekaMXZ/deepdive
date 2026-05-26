from __future__ import annotations

import unittest
from typing import Any

from backend.api.app import create_app
from backend.ids import new_uuid7
from fastapi.testclient import TestClient


class ApiDocumentsTest(unittest.TestCase):
    def test_documents_tree_endpoint_returns_nested_nodes(self) -> None:
        app = create_app()
        client = TestClient(app)
        headers = _auth_headers(client)
        analysis = client.post(
            "/api/analysis",
            json={"repository_url": "https://github.com/example/project.git", "ref": "main"},
            headers=headers,
        ).json()
        analysis_id = analysis["analysis_id"]
        app.state.document_service = FakeDocumentService(
            tree=[
                {
                    "node_id": str(new_uuid7()),
                    "node_type": "folder",
                    "document_id": None,
                    "title": "后端",
                    "slug": "backend",
                    "path": "backend",
                    "focus_area": None,
                    "sort_order": 10,
                    "status": None,
                    "version": None,
                    "section_count": 0,
                    "children": [
                        {
                            "node_id": str(new_uuid7()),
                            "node_type": "document",
                            "document_id": str(new_uuid7()),
                            "title": "认证与鉴权",
                            "slug": "auth-and-rbac",
                            "path": "backend/auth-and-rbac",
                            "focus_area": "backend authentication and authorization",
                            "sort_order": 10,
                            "status": "draft",
                            "version": 1,
                            "section_count": 2,
                            "children": [],
                        }
                    ],
                }
            ]
        )

        response = client.get(f"/api/analysis/{analysis_id}/documents/tree", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["items"][0]["title"], "后端")
        child = payload["items"][0]["children"][0]
        self.assertEqual(child["title"], "认证与鉴权")
        self.assertEqual(child["path"], "backend/auth-and-rbac")
        self.assertEqual(child["section_count"], 2)


class FakeDocumentService:
    def __init__(self, *, tree: list[dict[str, Any]]) -> None:
        self._tree = tree

    async def tree(self, *, analysis_id):
        del analysis_id
        return self._tree


def _auth_headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/api/auth/register",
        json={"email": "documents@example.com", "password": "correct horse battery staple"},
    )
    tokens = client.post(
        "/api/auth/login",
        json={"email": "documents@example.com", "password": "correct horse battery staple"},
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


if __name__ == "__main__":
    unittest.main()
