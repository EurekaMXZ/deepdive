import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyAnalysisStreamEvent,
  createAnalysisStreamItems,
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

test('builds a single analysis stream from reasoning, output, and tool events', () => {
  let state = createInitialAnalysisStreamState()

  state = applyAnalysisStreamEvent(state, {
    kind: 'reasoning_delta',
    text: '## 思考\n\n先看入口。',
    itemId: 'reasoning-1',
    replayId: '1',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'reasoning_delta',
    text: '\n\n再查配置。',
    itemId: 'reasoning-1',
    replayId: '2',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'output_delta',
    text: '# 输出\n\n',
    replayId: '3',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'output_delta',
    text: '已经定位主流程。',
    replayId: '4',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'tool_call',
    toolCallId: 'tool-1',
    toolName: 'search_file',
    arguments: { glob: '*.yml' },
    replayId: '5',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'tool_result',
    toolCallId: 'tool-1',
    toolName: 'search_file',
    ok: true,
    result: { matches: ['ci.yml'] },
    replayId: '6',
  })

  assert.deepEqual(createAnalysisStreamItems(state), [
    {
      id: 'reasoning-reasoning-1',
      type: 'reasoning',
      markdown: '## 思考\n\n先看入口。\n\n再查配置。',
      streaming: true,
      replayId: '2',
    },
    {
      id: 'output',
      type: 'output',
      markdown: '# 输出\n\n已经定位主流程。',
      streaming: true,
      replayId: '4',
    },
    {
      id: 'tool-tool-1',
      type: 'tool',
      toolCallId: 'tool-1',
      toolName: 'search_file',
      arguments: { glob: '*.yml' },
      ok: true,
      result: { matches: ['ci.yml'] },
      replayId: '6',
    },
  ])
})

test('merges final reasoning summary into streamed reasoning instead of rendering it twice', () => {
  let state = createInitialAnalysisStreamState()

  state = applyAnalysisStreamEvent(state, {
    kind: 'reasoning_delta',
    text: '先读取入口',
    itemId: 'rs_1',
    replayId: '1',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'reasoning_delta',
    text: '，再检查配置。',
    itemId: 'rs_1',
    replayId: '2',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'reasoning_done',
    text: '先读取入口，再检查配置。',
    itemId: 'rs_1',
    replayId: '3',
  })
  state = applyAnalysisStreamEvent(state, {
    kind: 'reasoning_summary',
    text: '先读取入口，再检查配置。',
    itemId: 'rs_1',
    replayId: '4',
  })

  assert.deepEqual(createAnalysisStreamItems(state), [
    {
      id: 'reasoning-rs_1',
      type: 'reasoning',
      markdown: '先读取入口，再检查配置。',
      streaming: false,
      replayId: '4',
    },
  ])
  assert.deepEqual(state.reasoningSummaries, ['先读取入口，再检查配置。'])
})

test('stores the latest todo update from analysis stream', () => {
  let state = createInitialAnalysisStreamState()

  state = applyAnalysisStreamEvent(state, {
    kind: 'todo_update',
    replayId: '10',
    todo: {
      version: 1,
      items: [{ id: 'read', title: 'Read files', status: 'completed' }],
      note: null,
    },
  })

  assert.deepEqual(state.todo, {
    version: 1,
    items: [{ id: 'read', title: 'Read files', status: 'completed' }],
    note: null,
  })
  assert.equal(state.lastReplayId, '10')
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
  assert.deepEqual(createAnalysisStreamItems(state), [
    {
      id: 'output',
      type: 'output',
      markdown: '分析',
      streaming: false,
    },
    {
      id: 'reasoning-current',
      type: 'reasoning',
      markdown: '先读取入口。',
      streaming: false,
    },
    {
      id: 'tool-tc_1',
      type: 'tool',
      toolCallId: 'tc_1',
      toolName: 'read_file',
      arguments: { path: 'README.md' },
      replayId: '2',
    },
  ])
  assert.equal(state.lastReplayId, '3')
  assert.equal(state.isTerminal, true)
})
