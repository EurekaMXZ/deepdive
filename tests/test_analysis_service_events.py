from __future__ import annotations

import unittest

from backend.api.records import AnalysisBatchCreateItem
from backend.api.services import InMemoryAnalysisService
from backend.events import EventType


class AnalysisServiceEventsTest(unittest.TestCase):
    def test_create_writes_analysis_requested_outbox_event(self) -> None:
        outbox = FakeOutboxSink()
        service = InMemoryAnalysisService(outbox=outbox)

        record = service.create(
            repository_url="https://github.com/example/project.git",
            requested_ref="main",
        )

        self.assertEqual(len(outbox.events), 1)
        event = outbox.events[0]
        self.assertEqual(event.event_type, EventType.ANALYSIS_REQUESTED)
        self.assertEqual(event.analysis_id, record.analysis_id)
        self.assertEqual(event.agent_id, record.agent_id)
        self.assertEqual(event.payload["repository_url"], record.repository_url)
        self.assertEqual(event.payload["requested_ref"], "main")

    def test_cancel_writes_analysis_cancel_requested_outbox_event(self) -> None:
        outbox = FakeOutboxSink()
        service = InMemoryAnalysisService(outbox=outbox)
        record = service.create(
            repository_url="https://github.com/example/project.git",
            requested_ref="main",
        )
        outbox.events.clear()

        service.cancel(record.analysis_id)

        self.assertEqual(len(outbox.events), 1)
        event = outbox.events[0]
        self.assertEqual(event.event_type, EventType.ANALYSIS_CANCEL_REQUESTED)
        self.assertEqual(event.analysis_id, record.analysis_id)
        self.assertEqual(event.agent_id, record.agent_id)

    def test_create_batch_writes_batch_submitted_without_dispatching_each_analysis(self) -> None:
        outbox = FakeOutboxSink()
        service = InMemoryAnalysisService(outbox=outbox)

        batch = service.create_batch(
            items=[
                AnalysisBatchCreateItem(
                    repository_url="https://github.com/example/one.git",
                    requested_ref="main",
                ),
                AnalysisBatchCreateItem(
                    repository_url="https://github.com/example/two.git",
                    requested_ref="main",
                ),
                AnalysisBatchCreateItem(
                    repository_url="https://github.com/example/three.git",
                    requested_ref="release",
                ),
            ],
            max_parallel=2,
        )

        self.assertEqual(batch.total_count, 3)
        self.assertEqual(batch.pending_count, 3)
        self.assertEqual(batch.active_count, 0)
        self.assertEqual(len(outbox.events), 1)
        event = outbox.events[0]
        self.assertEqual(event.event_type, EventType.ANALYSIS_BATCH_SUBMITTED)
        self.assertIsNone(event.analysis_id)
        self.assertEqual(event.payload["batch_id"], str(batch.batch_id))
        self.assertEqual(event.payload["max_parallel"], 2)


class FakeOutboxSink:
    def __init__(self) -> None:
        self.events = []

    def add(self, event) -> None:
        self.events.append(event)


if __name__ == "__main__":
    unittest.main()
