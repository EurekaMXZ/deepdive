import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyAnalysisStreamEvent,
  createInitialAnalysisStreamState,
  getAnalysisStatusMeta,
  isTerminalAnalysisStatus,
} from '../src/domain/analysis.ts'

test('maps backend and agent statuses into stable UI metadata', () => {
  assert.deepEqual(getAnalysisStatusMeta('queued'), {
    phase: 'pending',
    label: '排队中',
    terminal: false,
  })
  assert.deepEqual(getAnalysisStatusMeta('calling_model'), {
    phase: 'running',
    label: '模型分析中',
    terminal: false,
  })
  assert.equal(isTerminalAnalysisStatus('completed'), true)
  assert.equal(isTerminalAnalysisStatus('waiting_tool'), false)
})

test('reduces output, reasoning, tool, status, and terminal stream events for UI consumers', () => {
  let state = createInitialAnalysisStreamState()

  state = applyAnalysisStreamEvent(state, {
    kind: 'status',
    status: 'calling_model',
    replayId: '1',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'output_delta',
    text: '分析',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'reasoning_summary',
    text: '先读取入口。',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'tool_call',
    toolCallId: 'tc_1',
    toolName: 'read_file',
    arguments: { path: 'README.md' },
    replayId: '2',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'done',
    status: 'completed',
    responseId: 'resp_1',
    outputRef: 'agent-outputs/a/t.json',
    replayId: '3',
  })

  assert.equal(state.status, 'completed')
  assert.equal(state.outputText, '分析')
  assert.deepEqual(state.reasoningSummaries, ['先读取入口。'])
  assert.equal(state.timeline.length, 4)
  assert.equal(state.lastReplayId, '3')
  assert.equal(state.isTerminal, true)
})
