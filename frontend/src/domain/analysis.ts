export type AnalysisId = string
export type AgentId = string
export type SnapshotId = string

export type AnalysisStatus =
  | 'queued'
  | 'snapshotting'
  | 'running'
  | 'calling_model'
  | 'waiting_tool'
  | 'cancelling'
  | 'cancelled'
  | 'completed'
  | 'failed'
  | (string & {})

export type AnalysisPhase = 'pending' | 'running' | 'terminal' | 'unknown'

export type AnalysisStatusMeta = {
  phase: AnalysisPhase
  label: string
  terminal: boolean
}

export type Analysis = {
  analysisId: AnalysisId
  agentId: AgentId
  snapshotId: SnapshotId | null
  status: AnalysisStatus
  repositoryUrl: string
  requestedRef: string
  resolvedCommitSha: string | null
  errorCode: string | null
  errorMessage: string | null
  createdAt: string
  updatedAt: string
}

export type AnalysisCreated = Pick<
  Analysis,
  'analysisId' | 'agentId' | 'snapshotId' | 'status' | 'createdAt'
>

export type CreateAnalysisInput = {
  repositoryUrl: string
  ref: string
}

export type ListAnalysesInput = {
  status?: AnalysisStatus
  repositoryUrlHash?: string
  createdAfter?: string
  createdBefore?: string
  limit?: number
  cursor?: string
}

export type AnalysisListPage = {
  items: Analysis[]
  nextCursor: string | null
}

export type AnalysisSuggestion = {
  analysisId: AnalysisId
  agentId: AgentId
  snapshotId: SnapshotId | null
  status: AnalysisStatus
  repositoryLabel: string
  repositoryUrl: string
  requestedRef: string
  resolvedCommitSha: string | null
  updatedAt: string
}

export type ListAnalysisSuggestionsInput = {
  repositoryQuery: string
  limit?: number
}

export type AnalysisSuggestionListPage = {
  items: AnalysisSuggestion[]
}

export type AnalysisTodoStatus = 'pending' | 'in_progress' | 'completed'

export type AnalysisTodoItem = {
  id: string
  title: string
  status: AnalysisTodoStatus
}

export type AnalysisTodoList = {
  version: number
  items: AnalysisTodoItem[]
  note: string | null
}

export type AnalysisStreamEvent =
  | {
      kind: 'status'
      status: AnalysisStatus
      replayId?: string
    }
  | {
      kind: 'output_delta'
      text: string
      replayId?: string
    }
  | {
      kind: 'reasoning_delta'
      text: string
      itemId?: string
      responseId?: string
      replayId?: string
    }
  | {
      kind: 'reasoning_summary'
      text: string
      itemId?: string
      responseId?: string
      replayId?: string
    }
  | {
      kind: 'reasoning_done'
      text?: string
      itemId?: string
      responseId?: string
      replayId?: string
    }
  | {
      kind: 'tool_call'
      toolCallId?: string
      toolName: string
      arguments: Record<string, unknown>
      replayId?: string
    }
  | {
      kind: 'tool_result'
      toolCallId?: string
      toolName?: string
      ok?: boolean
      result?: unknown
      error?: unknown
      resultRef?: string
      evidenceIds?: string[]
      truncated?: boolean
      nextCursor?: string | null
      replayId?: string
    }
  | {
      kind: 'todo_update'
      todo: AnalysisTodoList
      replayId?: string
    }
  | {
      kind: 'compact'
      tokenEstimate?: number
      threshold?: number
      replayId?: string
    }
  | {
      kind: 'attempt_failed'
      turnId?: string
      attempt?: number
      errorCode?: string
      message?: string
      retryable?: boolean
      supersedesStreamDeltas?: boolean
      replayId?: string
    }
  | {
      kind: 'done'
      status: AnalysisStatus
      responseId?: string
      outputRef?: string
      replayId?: string
    }
  | {
      kind: 'error'
      code?: string
      message?: string
      retryable?: boolean
      replayId?: string
    }
  | {
      kind: 'raw'
      event: string
      data: unknown
      replayId?: string
    }

export type AnalysisStreamItem =
  | {
      id: string
      type: 'reasoning'
      markdown: string
      streaming: boolean
      replayId?: string
    }
  | {
      id: string
      type: 'output'
      markdown: string
      streaming: boolean
      replayId?: string
    }
  | {
      id: string
      type: 'tool'
      toolCallId?: string
      toolName: string
      arguments: Record<string, unknown>
      ok?: boolean
      result?: unknown
      error?: unknown
      resultRef?: string
      evidenceIds?: string[]
      truncated?: boolean
      nextCursor?: string | null
      replayId?: string
    }

export type AnalysisStreamState = {
  status: AnalysisStatus | null
  outputText: string
  reasoningSummaries: string[]
  streamItems: AnalysisStreamItem[]
  todo: AnalysisTodoList | null
  lastReplayId: string | null
  isTerminal: boolean
  error: { code?: string; message?: string; retryable?: boolean } | null
}

const STATUS_META: Record<string, AnalysisStatusMeta> = {
  queued: { phase: 'pending', label: '排队中', terminal: false },
  snapshotting: { phase: 'running', label: '正在创建仓库快照', terminal: false },
  running: { phase: 'running', label: '分析中', terminal: false },
  calling_model: { phase: 'running', label: '模型分析中', terminal: false },
  waiting_tool: { phase: 'running', label: '正在读取/搜索源码', terminal: false },
  cancelling: { phase: 'running', label: '正在取消', terminal: false },
  cancelled: { phase: 'terminal', label: '已取消', terminal: true },
  completed: { phase: 'terminal', label: '已完成', terminal: true },
  failed: { phase: 'terminal', label: '失败', terminal: true },
}

export function getAnalysisStatusMeta(status: AnalysisStatus): AnalysisStatusMeta {
  return STATUS_META[status] ?? {
    phase: 'unknown',
    label: status,
    terminal: false,
  }
}

export function isTerminalAnalysisStatus(status: AnalysisStatus): boolean {
  return getAnalysisStatusMeta(status).terminal
}

export function createInitialAnalysisStreamState(): AnalysisStreamState {
  return {
    status: null,
    outputText: '',
    reasoningSummaries: [],
    streamItems: [],
    todo: null,
    lastReplayId: null,
    isTerminal: false,
    error: null,
  }
}

export function createAnalysisStreamItems(
  state: AnalysisStreamState,
): AnalysisStreamItem[] {
  return state.streamItems
}

function toolItemKey(toolCallId?: string, toolName?: string): string {
  return toolCallId ?? `tool-name:${toolName ?? 'unknown'}`
}

export function applyAnalysisStreamEvent(
  state: AnalysisStreamState,
  event: AnalysisStreamEvent,
): AnalysisStreamState {
  const nextReplayId = event.replayId ?? state.lastReplayId

  if (event.kind === 'status') {
    return {
      ...state,
      status: event.status,
      lastReplayId: nextReplayId,
      isTerminal: isTerminalAnalysisStatus(event.status),
    }
  }

  if (event.kind === 'output_delta') {
    return {
      ...state,
      outputText: state.outputText + event.text,
      streamItems: appendOutputDelta(state.streamItems, event.text, event.replayId, state.isTerminal),
      lastReplayId: nextReplayId,
    }
  }

  if (event.kind === 'reasoning_delta') {
    return {
      ...state,
      streamItems: appendReasoningDelta(
        state.streamItems,
        event.text,
        reasoningStreamItemId(event.itemId, event.responseId),
        event.replayId,
        state.isTerminal,
      ),
      lastReplayId: nextReplayId,
    }
  }

  if (event.kind === 'reasoning_summary') {
    return {
      ...state,
      reasoningSummaries: [...state.reasoningSummaries, event.text],
      streamItems: mergeReasoningSummary(
        state.streamItems,
        event.text,
        reasoningStreamItemId(event.itemId, event.responseId),
        event.replayId,
      ),
      lastReplayId: nextReplayId,
    }
  }

  if (event.kind === 'reasoning_done') {
    return {
      ...state,
      streamItems: finishReasoningItem(
        state.streamItems,
        event.text,
        reasoningStreamItemId(event.itemId, event.responseId),
        event.replayId,
      ),
      lastReplayId: nextReplayId,
    }
  }

  if (event.kind === 'tool_call') {
    return {
      ...state,
      lastReplayId: nextReplayId,
      streamItems: appendToolCall(state.streamItems, event),
    }
  }

  if (event.kind === 'tool_result') {
    return {
      ...state,
      lastReplayId: nextReplayId,
      streamItems: appendToolResult(state.streamItems, event),
    }
  }

  if (event.kind === 'todo_update') {
    return {
      ...state,
      todo: event.todo,
      lastReplayId: nextReplayId,
    }
  }

  if (event.kind === 'compact') {
    return {
      ...state,
      lastReplayId: nextReplayId,
    }
  }

  if (event.kind === 'attempt_failed') {
    return {
      ...state,
      lastReplayId: nextReplayId,
    }
  }

  if (event.kind === 'done') {
    return {
      ...state,
      status: event.status,
      lastReplayId: nextReplayId,
      isTerminal: true,
      streamItems: finishStreamingItems(state.streamItems),
    }
  }

  if (event.kind === 'error') {
    return {
      ...state,
      status: 'failed',
      lastReplayId: nextReplayId,
      isTerminal: true,
      streamItems: finishStreamingItems(state.streamItems),
      error: {
        code: event.code,
        message: event.message,
        retryable: event.retryable,
      },
    }
  }

  return {
    ...state,
    lastReplayId: nextReplayId,
  }
}

function appendOutputDelta(
  items: AnalysisStreamItem[],
  text: string,
  replayId: string | undefined,
  isTerminal: boolean,
): AnalysisStreamItem[] {
  const index = items.findIndex((item) => item.type === 'output')
  if (index < 0) {
    return [
      ...items,
      withoutUndefinedOptionalFields({
        id: 'output',
        type: 'output',
        markdown: text,
        streaming: !isTerminal,
        replayId,
      }),
    ]
  }

  return items.map((item, itemIndex) =>
    itemIndex === index && item.type === 'output'
      ? {
          ...item,
          markdown: item.markdown + text,
          streaming: !isTerminal,
          replayId,
        }
      : item,
  )
}

function appendReasoningDelta(
  items: AnalysisStreamItem[],
  text: string,
  id: string,
  replayId: string | undefined,
  isTerminal: boolean,
): AnalysisStreamItem[] {
  const index = items.findIndex((item) => item.id === id && item.type === 'reasoning')
  if (index < 0) {
    return [
      ...items,
      withoutUndefinedOptionalFields({
        id,
        type: 'reasoning',
        markdown: text,
        streaming: !isTerminal,
        replayId,
      }),
    ]
  }

  return items.map((item, itemIndex) =>
    itemIndex === index && item.type === 'reasoning'
      ? {
          ...item,
          markdown: item.markdown + text,
          streaming: !isTerminal,
          replayId,
        }
      : item,
  )
}

function mergeReasoningSummary(
  items: AnalysisStreamItem[],
  markdown: string,
  id: string,
  replayId: string | undefined,
): AnalysisStreamItem[] {
  const index = items.findIndex((item) => item.id === id && item.type === 'reasoning')
  if (index >= 0) {
    return items.map((item, itemIndex) =>
      itemIndex === index && item.type === 'reasoning'
        ? {
            ...item,
            markdown,
            streaming: false,
            replayId,
          }
        : item,
    )
  }

  return [
    ...items,
    withoutUndefinedOptionalFields({
      id,
      type: 'reasoning',
      markdown,
      streaming: false,
      replayId,
    }),
  ]
}

function finishReasoningItem(
  items: AnalysisStreamItem[],
  markdown: string | undefined,
  id: string,
  replayId: string | undefined,
): AnalysisStreamItem[] {
  const index = items.findIndex((item) => item.id === id && item.type === 'reasoning')
  if (index < 0) {
    if (!markdown) {
      return items
    }
    return mergeReasoningSummary(items, markdown, id, replayId)
  }

  return items.map((item, itemIndex) =>
    itemIndex === index && item.type === 'reasoning'
      ? {
          ...item,
          markdown: markdown || item.markdown,
          streaming: false,
          replayId,
        }
      : item,
  )
}

function appendToolCall(
  items: AnalysisStreamItem[],
  event: Extract<AnalysisStreamEvent, { kind: 'tool_call' }>,
): AnalysisStreamItem[] {
  return [
    ...items,
    {
      id: `tool-${event.toolCallId ?? event.replayId ?? items.length}`,
      type: 'tool',
      toolCallId: event.toolCallId,
      toolName: event.toolName,
      arguments: event.arguments,
      replayId: event.replayId,
    },
  ]
}

function appendToolResult(
  items: AnalysisStreamItem[],
  event: Extract<AnalysisStreamEvent, { kind: 'tool_result' }>,
): AnalysisStreamItem[] {
  const resultPatch = withoutUndefinedOptionalFields({
    ok: event.ok,
    result: event.result,
    error: event.error,
    resultRef: event.resultRef,
    evidenceIds: event.evidenceIds,
    truncated: event.truncated,
    nextCursor: event.nextCursor,
    replayId: event.replayId,
  })
  const index = items.findIndex(
    (item) =>
      item.type === 'tool' &&
      toolItemKey(item.toolCallId, item.toolName) === toolItemKey(event.toolCallId, event.toolName),
  )

  if (index < 0) {
    return [
      ...items,
      {
        id: `tool-${event.toolCallId ?? event.replayId ?? items.length}`,
        type: 'tool',
        toolCallId: event.toolCallId,
        toolName: event.toolName ?? 'unknown_tool',
        arguments: {},
        ...resultPatch,
      },
    ]
  }

  return items.map((item, itemIndex) =>
    itemIndex === index && item.type === 'tool'
      ? {
          ...item,
          ...resultPatch,
        }
      : item,
  )
}

function finishStreamingItems(items: AnalysisStreamItem[]): AnalysisStreamItem[] {
  return items.map((item) =>
    item.type === 'reasoning' || item.type === 'output'
      ? {
          ...item,
          streaming: false,
        }
      : item,
  )
}

function reasoningStreamItemId(
  itemId?: string,
  responseId?: string,
  replayId?: string,
): string {
  return `reasoning-${itemId ?? responseId ?? replayId ?? 'current'}`
}

function withoutUndefinedOptionalFields<T extends Record<string, unknown>>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== undefined),
  ) as T
}
