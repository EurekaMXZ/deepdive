import assert from 'node:assert/strict'
import test from 'node:test'

import {
  SseDecoder,
  normalizeAnalysisSseEvent,
  parseSseEvents,
} from '../src/api/sse.ts'

test('parses persisted SSE events with replay id and JSON payload', () => {
  const events = parseSseEvents('id: 2\nevent: delta\ndata: {"text":"hello"}\n\n')

  assert.deepEqual(events, [
    {
      id: '2',
      event: 'delta',
      data: { text: 'hello' },
      rawData: '{"text":"hello"}',
    },
  ])
})

test('decodes chunked SSE frames and ignores keepalive comments', () => {
  const decoder = new SseDecoder()

  assert.deepEqual(decoder.push(': keepalive\n\nid: 3\nevent: status\n'), [])
  assert.deepEqual(decoder.push('data: {"status":"running"}\n\n'), [
    {
      id: '3',
      event: 'status',
      data: { status: 'running' },
      rawData: '{"status":"running"}',
    },
  ])
})

test('normalizes backend persisted and live model events into analysis stream events', () => {
  assert.deepEqual(
    normalizeAnalysisSseEvent({
      id: '7',
      event: 'tool_call',
      data: {
        tool_call_id: 'tc_1',
        tool_name: 'read_file',
        arguments: { path: 'README.md' },
      },
      rawData: '{}',
    }),
    {
      kind: 'tool_call',
      replayId: '7',
      toolCallId: 'tc_1',
      toolName: 'read_file',
      arguments: { path: 'README.md' },
    },
  )

  assert.deepEqual(
    normalizeAnalysisSseEvent({
      event: 'response.output_text.delta',
      data: { type: 'response.output_text.delta', delta: '实时' },
      rawData: '{}',
    }),
    {
      kind: 'output_delta',
      text: '实时',
    },
  )

  assert.deepEqual(
    normalizeAnalysisSseEvent({
      event: 'model_reasoning_summary.delta',
      data: { type: 'model_reasoning_summary.delta', text: '隐藏的增量' },
      rawData: '{}',
    }),
    {
      kind: 'raw',
      event: 'model_reasoning_summary.delta',
      data: { type: 'model_reasoning_summary.delta', text: '隐藏的增量' },
    },
  )
})
