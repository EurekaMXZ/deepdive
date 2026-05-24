from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from backend.api.app import create_app
from backend.api.routes import _polling_sse_event_records
from backend.api.services import AnalysisRecord, InMemoryAnalysisService
from backend.ids import new_uuid7
from fastapi.testclient import TestClient


class ApiSseReplayTest(unittest.TestCase):
    def test_events_endpoint_replays_persisted_events_after_last_event_id(self) -> None:
        app = create_app()
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        now = datetime.now(UTC)
        service = FakeAnalysisService(
            AnalysisRecord(
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=None,
                status="running",
                repository_url="https://github.com/example/project",
                requested_ref="main",
                resolved_commit_sha=None,
                created_at=now,
                updated_at=now,
            ),
            events=[
                {"seq": 1, "event_type": "status", "payload_json": {"status": "running"}},
                {"seq": 2, "event_type": "delta", "payload_json": {"text": "hello"}},
                {"seq": 3, "event_type": "done", "payload_json": {"status": "completed"}},
            ],
        )
        app.state.analysis_service = service

        response = TestClient(app).get(
            f"/analysis/{analysis_id}/events",
            headers={"Last-Event-ID": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("id: 1", response.text)
        self.assertIn("id: 2", response.text)
        self.assertIn("event: delta", response.text)
        self.assertIn("id: 3", response.text)

    def test_events_endpoint_replays_persisted_reasoning_summary(self) -> None:
        app = create_app()
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        now = datetime.now(UTC)
        service = FakeAnalysisService(
            AnalysisRecord(
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=None,
                status="running",
                repository_url="https://github.com/example/project",
                requested_ref="main",
                resolved_commit_sha=None,
                created_at=now,
                updated_at=now,
            ),
            events=[
                {"seq": 1, "event_type": "status", "payload_json": {"status": "calling_model"}},
                {
                    "seq": 2,
                    "event_type": "model_reasoning_summary",
                    "payload_json": {
                        "type": "model_reasoning_summary",
                        "text": "我会先查看仓库结构, 再读取入口文件。",
                        "item_id": "rs_1",
                        "response_id": "resp_1",
                    },
                },
                {"seq": 3, "event_type": "done", "payload_json": {"status": "completed"}},
            ],
        )
        app.state.analysis_service = service

        response = TestClient(app).get(
            f"/analysis/{analysis_id}/events",
            headers={"Last-Event-ID": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("id: 1", response.text)
        self.assertIn("id: 2", response.text)
        self.assertIn("event: model_reasoning_summary", response.text)
        self.assertIn("我会先查看仓库结构", response.text)

    def test_events_endpoint_continues_polling_until_terminal_status(self) -> None:
        app = create_app()
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        now = datetime.now(UTC)
        service = FakeAnalysisService(
            AnalysisRecord(
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=None,
                status="running",
                repository_url="https://github.com/example/project",
                requested_ref="main",
                resolved_commit_sha=None,
                created_at=now,
                updated_at=now,
            ),
            events=[
                {"seq": 1, "event_type": "status", "payload_json": {"status": "running"}},
                {"seq": 2, "event_type": "done", "payload_json": {"status": "completed"}},
            ],
        )
        service.statuses = ["running", "completed"]
        app.state.analysis_service = service

        response = TestClient(app).get(
            f"/analysis/{analysis_id}/events",
            params={"poll_interval_seconds": 0, "idle_timeout_seconds": 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("id: 1", response.text)
        self.assertIn("id: 2", response.text)
        self.assertGreaterEqual(service.stream_calls, 2)

    def test_events_endpoint_replays_terminal_event_after_status_turns_terminal(self) -> None:
        app = create_app()
        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        now = datetime.now(UTC)
        service = FakeAnalysisService(
            AnalysisRecord(
                analysis_id=analysis_id,
                agent_id=agent_id,
                snapshot_id=None,
                status="running",
                repository_url="https://github.com/example/project",
                requested_ref="main",
                resolved_commit_sha=None,
                created_at=now,
                updated_at=now,
            ),
            events=[
                {"seq": 1, "event_type": "status", "payload_json": {"status": "running"}},
                {"seq": 2, "event_type": "done", "payload_json": {"status": "completed"}},
            ],
        )
        service.statuses = ["completed"]
        service.release_events_after_status_checks = 1
        app.state.analysis_service = service

        response = TestClient(app).get(
            f"/analysis/{analysis_id}/events",
            params={"poll_interval_seconds": 0, "idle_timeout_seconds": 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("id: 1", response.text)
        self.assertIn("id: 2", response.text)
        self.assertIn("event: done", response.text)

    def test_polling_events_heartbeats_instead_of_closing_while_running_idle(self) -> None:
        async def run_test() -> None:
            analysis_id = new_uuid7()
            agent_id = new_uuid7()
            now = datetime.now(UTC)
            service = FakeAnalysisService(
                AnalysisRecord(
                    analysis_id=analysis_id,
                    agent_id=agent_id,
                    snapshot_id=None,
                    status="running",
                    repository_url="https://github.com/example/project",
                    requested_ref="main",
                    resolved_commit_sha=None,
                    created_at=now,
                    updated_at=now,
                ),
                events=[
                    {"seq": 1, "event_type": "status", "payload_json": {"status": "calling_model"}},
                ],
            )

            stream = _polling_sse_event_records(
                service,
                analysis_id,
                after_seq=0,
                poll_interval_seconds=0,
                idle_timeout_seconds=0.001,
            )
            try:
                first_event = await anext(stream)
                heartbeat = await asyncio.wait_for(anext(stream), timeout=1)
            finally:
                await stream.aclose()

            self.assertIn("event: status", first_event)
            self.assertEqual(heartbeat, ": keepalive\n\n")
            self.assertGreaterEqual(service.status_calls, 1)

        asyncio.run(run_test())


class FakeAnalysisService(InMemoryAnalysisService):
    supports_live_events = True

    def __init__(self, record: AnalysisRecord, *, events: list[dict]) -> None:
        self._record = record
        self._events = events
        self.statuses: list[str] = []
        self.stream_calls = 0
        self.status_calls = 0
        self.release_events_after_status_checks: int | None = None

    def get(self, analysis_id):
        return self._record if analysis_id == self._record.analysis_id else None

    def stream_events(self, analysis_id, *, after_seq: int = 0):
        del analysis_id
        self.stream_calls += 1
        visible_event_count = self.stream_calls
        if self.release_events_after_status_checks is not None:
            visible_event_count = 1
            if self.status_calls >= self.release_events_after_status_checks:
                visible_event_count = len(self._events)
        return [event for event in self._events if event["seq"] > after_seq and event["seq"] <= visible_event_count]

    async def analysis_status(self, analysis_id):
        del analysis_id
        self.status_calls += 1
        if self.statuses:
            self._record.status = self.statuses.pop(0)
        await asyncio.sleep(0)
        return self._record.status


if __name__ == "__main__":
    unittest.main()
