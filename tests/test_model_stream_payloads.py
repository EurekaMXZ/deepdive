from __future__ import annotations

import unittest


class ModelStreamPayloadsTest(unittest.TestCase):
    def test_completed_response_stream_payload_is_lightweight(self) -> None:
        from backend.events.model_stream_payloads import completed_response_stream_payload

        payload = completed_response_stream_payload(
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

    def test_reasoning_summary_text_stream_payload_converts_delta_and_done(self) -> None:
        from backend.events.model_stream_payloads import model_reasoning_summary_text_stream_payload

        delta = model_reasoning_summary_text_stream_payload(
            "response.reasoning_summary_text.delta",
            {
                "type": "response.reasoning_summary_text.delta",
                "delta": "先查看目录",
                "item_id": "rs_1",
                "response_id": "resp_1",
                "summary_index": 0,
            },
        )
        done = model_reasoning_summary_text_stream_payload(
            "response.reasoning_summary_text.done",
            {
                "type": "response.reasoning_summary_text.done",
                "text": "先查看目录",
                "item_id": "rs_1",
                "response_id": "resp_1",
                "summary_index": 0,
            },
        )

        self.assertEqual(
            delta,
            (
                "model_reasoning_summary.delta",
                {
                    "type": "model_reasoning_summary.delta",
                    "text": "先查看目录",
                    "item_id": "rs_1",
                    "response_id": "resp_1",
                    "summary_index": 0,
                },
            ),
        )
        self.assertEqual(
            done,
            (
                "model_reasoning_summary.done",
                {
                    "type": "model_reasoning_summary.done",
                    "text": "先查看目录",
                    "item_id": "rs_1",
                    "response_id": "resp_1",
                    "summary_index": 0,
                },
            ),
        )

    def test_reasoning_summary_stream_payloads_extract_completed_response_summaries(self) -> None:
        from backend.events.model_stream_payloads import model_reasoning_summary_stream_payloads

        payloads = model_reasoning_summary_stream_payloads(
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "output": [
                        {
                            "id": "rs_1",
                            "type": "reasoning",
                            "summary": [{"type": "summary_text", "text": "已读取 README。"}],
                        },
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "final"}],
                        },
                    ],
                },
            }
        )

        self.assertEqual(
            payloads,
            [
                {
                    "type": "model_reasoning_summary",
                    "text": "已读取 README。",
                    "item_id": "rs_1",
                    "response_id": "resp_1",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
