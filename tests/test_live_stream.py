from __future__ import annotations

import asyncio
import unittest

from backend.ids import new_uuid7


class LiveModelStreamTest(unittest.TestCase):
    def test_live_model_stream_event_round_trips_and_uses_analysis_key(self) -> None:
        from backend.events.live_stream import (
            LIVE_MODEL_STREAM_TOPIC,
            LiveModelStreamEvent,
            live_model_stream_key,
        )

        analysis_id = new_uuid7()
        agent_id = new_uuid7()
        turn_id = new_uuid7()
        event = LiveModelStreamEvent.new(
            analysis_id=analysis_id,
            agent_id=agent_id,
            turn_id=turn_id,
            attempt=2,
            stream_seq=3,
            event_name="response.output_text.delta",
            payload={"type": "response.output_text.delta", "delta": "片段"},
            response_id="resp_1",
        )

        restored = LiveModelStreamEvent.from_json(event.to_json())

        self.assertEqual(LIVE_MODEL_STREAM_TOPIC, "deepdive.agent.stream")
        self.assertEqual(restored, event)
        self.assertEqual(live_model_stream_key(event), str(analysis_id).encode())

    def test_completed_live_event_is_lightweight(self) -> None:
        from backend.events.live_stream import completed_live_payload

        payload = completed_live_payload(
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "large"}]}],
                    "usage": {"total_tokens": 10},
                },
            }
        )

        self.assertEqual(payload, {"type": "response.completed", "response_id": "resp_1"})

    def test_live_stream_hub_fanout_is_scoped_by_analysis_id(self) -> None:
        from backend.api.live_stream import LiveStreamHub
        from backend.events.live_stream import LiveModelStreamEvent

        async def run_test() -> None:
            analysis_id = new_uuid7()
            other_analysis_id = new_uuid7()
            agent_id = new_uuid7()
            turn_id = new_uuid7()
            hub = LiveStreamHub(queue_size=10)
            subscription = hub.subscribe(analysis_id)
            other_event = LiveModelStreamEvent.new(
                analysis_id=other_analysis_id,
                agent_id=agent_id,
                turn_id=turn_id,
                attempt=1,
                stream_seq=1,
                event_name="response.output_text.delta",
                payload={"type": "response.output_text.delta", "delta": "other"},
            )
            event = LiveModelStreamEvent.new(
                analysis_id=analysis_id,
                agent_id=agent_id,
                turn_id=turn_id,
                attempt=1,
                stream_seq=2,
                event_name="response.output_text.delta",
                payload={"type": "response.output_text.delta", "delta": "visible"},
            )

            await hub.publish(other_event)
            await hub.publish(event)
            received = await asyncio.wait_for(subscription.get(), timeout=1)
            subscription.close()

            self.assertEqual(received, event)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
