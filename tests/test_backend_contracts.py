from __future__ import annotations

import unittest


class ApiStreamContractsTest(unittest.TestCase):
    def test_stream_event_contract_formats_and_detects_terminal_events(self) -> None:
        from backend.api.sse import format_sse_event, is_terminal_stream_event

        event = {
            "seq": 7,
            "event_type": "analysis_error",
            "payload_json": {"error": {"code": "MODEL_FAILED", "message": "model failed"}},
        }

        self.assertEqual(
            format_sse_event(event),
            'id: 7\nevent: analysis_error\ndata: {"error":{"code":"MODEL_FAILED","message":"model failed"}}\n\n',
        )
        self.assertTrue(is_terminal_stream_event(event))

    def test_tool_events_are_formatted_with_frontend_safe_minimum_payloads(self) -> None:
        from backend.api.sse import format_sse_event

        tool_call = {
            "seq": 8,
            "event_type": "tool_call",
            "payload_json": {
                "tool_call_id": "tc_1",
                "tool_name": "read_file",
                "arguments": {"path": "README.md"},
                "openai_call_id": "call_1",
                "instructions": "hidden system instructions",
            },
        }
        tool_result = {
            "seq": 9,
            "event_type": "tool_result",
            "payload_json": {
                "tool_call_id": "tc_1",
                "ok": True,
                "tool_name": "read_file",
                "snapshot_id": "snapshot-hidden",
                "result": {
                    "path": "README.md",
                    "content": "visible",
                    "instructions": "hidden system instructions",
                    "system": "hidden",
                    "developer": "hidden",
                },
                "result_ref": "tool-results/tc_1.json",
                "evidence_ids": ["ev_1"],
                "truncated": False,
                "next_cursor": None,
            },
        }

        formatted_call = format_sse_event(tool_call)
        formatted_result = format_sse_event(tool_result)

        self.assertEqual(
            formatted_call,
            'id: 8\nevent: tool_call\ndata: {"tool_call_id":"tc_1","tool_name":"read_file","arguments":{"path":"README.md"}}\n\n',
        )
        self.assertIn('"result":{"path":"README.md","content":"visible"}', formatted_result)
        self.assertIn('"result_ref":"tool-results/tc_1.json"', formatted_result)
        self.assertNotIn("instructions", formatted_result)
        self.assertNotIn("system", formatted_result)
        self.assertNotIn("developer", formatted_result)
        self.assertNotIn("snapshot-hidden", formatted_result)

    def test_stream_error_payload_uses_error_envelope(self) -> None:
        from backend.api.stream_schemas import error_event_payload

        self.assertEqual(
            error_event_payload(code="MODEL_FAILED", message="model failed", retryable=True),
            {"error": {"code": "MODEL_FAILED", "message": "model failed", "retryable": True}},
        )

class EventContractsTest(unittest.TestCase):
    def test_agent_inbox_topic_name_describes_event_routing_not_commands_only(self) -> None:
        from backend.events.routing import AGENT_INBOX_TOPICS

        self.assertIn("SnapshotReady", {event_type.value for event_type in AGENT_INBOX_TOPICS})


if __name__ == "__main__":
    unittest.main()
