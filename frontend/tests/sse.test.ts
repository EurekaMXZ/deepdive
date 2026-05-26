import assert from 'node:assert/strict'
import test from 'node:test'

import {
  SseDecoder,
  normalizeAnalysisSseEvent,
  parseSseEvents,
  subscribeAnalysisEvents,
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
      id: '8',
      event: 'agent_message',
      data: {
        type: 'agent_message',
        text: '阶段性说明',
        response_id: 'resp_1',
        item_id: 'msg_1',
        phase: 'commentary',
      },
      rawData: '{}',
    }),
    {
      kind: 'output_delta',
      replayId: '8',
      text: '阶段性说明',
    },
  )

  assert.deepEqual(
    normalizeAnalysisSseEvent({
      id: '9',
      event: 'response.commentary.output_text.delta',
      data: { type: 'response.commentary.output_text.delta', delta: 'commentary 增量' },
      rawData: '{}',
    }),
    {
      kind: 'output_delta',
      replayId: '9',
      text: 'commentary 增量',
    },
  )

  assert.deepEqual(
    normalizeAnalysisSseEvent({
      event: 'model_reasoning_summary.delta',
      data: { type: 'model_reasoning_summary.delta', text: '隐藏的增量' },
      rawData: '{}',
    }),
    {
      kind: 'reasoning_delta',
      text: '隐藏的增量',
    },
  )

  assert.deepEqual(
    normalizeAnalysisSseEvent({
      id: '8',
      event: 'model_reasoning_summary.done',
      data: { type: 'model_reasoning_summary.done', text: '完整 summary', item_id: 'rs_1' },
      rawData: '{}',
    }),
    {
      kind: 'reasoning_done',
      text: '完整 summary',
      itemId: 'rs_1',
      replayId: '8',
    },
  )

  assert.deepEqual(
    normalizeAnalysisSseEvent({
      id: '9',
      event: 'model_reasoning.delta',
      data: { delta: '后端新增 reasoning 流', item_id: 'rs_1' },
      rawData: '{}',
    }),
    {
      kind: 'reasoning_delta',
      text: '后端新增 reasoning 流',
      itemId: 'rs_1',
      replayId: '9',
    },
  )
})

test('normalizes todo update events from analysis stream', () => {
  assert.deepEqual(
    normalizeAnalysisSseEvent({
      id: '10',
      event: 'todo_update',
      data: {
        version: 2,
        items: [
          { id: 'inspect-entry', title: 'Inspect entrypoint', status: 'completed' },
          { id: 'trace-config', title: 'Trace config loading', status: 'in_progress' },
          { id: 'invalid', title: 'Invalid item', status: 'blocked' },
        ],
        note: 'Current plan',
      },
      rawData: '{}',
    }),
    {
      kind: 'todo_update',
      replayId: '10',
      todo: {
        version: 2,
        items: [
          { id: 'inspect-entry', title: 'Inspect entrypoint', status: 'completed' },
          { id: 'trace-config', title: 'Trace config loading', status: 'in_progress' },
        ],
        note: 'Current plan',
      },
    },
  )
})

test('subscribeAnalysisEvents sends bearer token and replay headers', async () => {
  const requests: Array<{ url: string; init: RequestInit }> = []

  await subscribeAnalysisEvents({
    analysisId: 'analysis-1',
    baseUrl: 'http://api.test/',
    accessToken: 'access-token',
    lastEventId: '12',
    fetch: async (url, init = {}) => {
      requests.push({ url: String(url), init })
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(new TextEncoder().encode('id: 13\nevent: status\ndata: {"status":"completed"}\n\n'))
            controller.close()
          },
        }),
        { status: 200, headers: { 'content-type': 'text/event-stream' } },
      )
    },
    onEvent() {},
  })

  assert.equal(requests[0].url, 'http://api.test/analysis/analysis-1/events')
  assert.equal(new Headers(requests[0].init.headers).get('authorization'), 'Bearer access-token')
  assert.equal(new Headers(requests[0].init.headers).get('last-event-id'), '12')
})
