from __future__ import annotations

import unittest

from backend.events import EventEnvelope, EventType, event_topic, outbox_payload
from backend.ids import new_uuid7


class EventLayerTest(unittest.TestCase):
    def test_event_envelope_round_trips_through_json(self) -> None:
        analysis_id = new_uuid7()
        event = EventEnvelope.new(
            event_type=EventType.ANALYSIS_REQUESTED,
            analysis_id=analysis_id,
            payload={"repository_url": "https://github.com/example/project.git"},
        )

        restored = EventEnvelope.from_json(event.to_json())

        self.assertEqual(restored.event_id, event.event_id)
        self.assertEqual(restored.schema_version, 1)
        self.assertEqual(restored.event_type, EventType.ANALYSIS_REQUESTED)
        self.assertEqual(restored.analysis_id, analysis_id)
        self.assertEqual(restored.correlation_id, analysis_id)
        self.assertEqual(restored.payload["repository_url"], "https://github.com/example/project.git")

    def test_outbox_payload_is_json_serializable(self) -> None:
        event = EventEnvelope.new(
            event_type=EventType.TOOL_CALL_REQUESTED,
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            payload={"tool_call_id": str(new_uuid7())},
        )

        payload = outbox_payload(event)

        self.assertEqual(payload["event_type"], EventType.TOOL_CALL_REQUESTED.value)
        self.assertEqual(EventEnvelope.from_json_value(payload["payload_json"]), event)

    def test_unknown_event_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EventEnvelope.new(event_type="UnknownEvent", payload={})

    def test_dlq_event_routes_to_dlq_topic(self) -> None:
        event = EventEnvelope.new(
            event_type=EventType.EVENT_PROCESSING_FAILED,
            payload={"original_event_id": str(new_uuid7())},
        )

        self.assertEqual(event_topic(event), "deepdive.dlq")

    def test_agent_continuation_events_route_to_agent_commands(self) -> None:
        for event_type in (
            EventType.SNAPSHOT_READY,
            EventType.TOOL_CALL_COMPLETED,
            EventType.TOOL_CALL_FAILED,
            EventType.TOOL_CALL_DENIED,
        ):
            event = EventEnvelope.new(event_type=event_type, analysis_id=new_uuid7(), agent_id=new_uuid7())

            self.assertEqual(event_topic(event), "deepdive.agent.commands")


if __name__ == "__main__":
    unittest.main()
