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
      kind: 'reasoning_summary'
      text: string
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

export type AnalysisTimelineItem =
  | {
      type: 'status'
      status: AnalysisStatus
      replayId?: string
    }
  | {
      type: 'reasoning_summary'
      text: string
      replayId?: string
    }
  | {
      type: 'tool_call'
      toolCallId?: string
      toolName: string
      arguments: Record<string, unknown>
      replayId?: string
    }
  | {
      type: 'tool_result'
      toolCallId?: string
      toolName?: string
      ok?: boolean
      result?: unknown
      error?: unknown
      replayId?: string
    }
  | {
      type: 'compact'
      tokenEstimate?: number
      threshold?: number
      replayId?: string
    }
  | {
      type: 'attempt_failed'
      message?: string
      retryable?: boolean
      replayId?: string
    }
  | {
      type: 'error'
      code?: string
      message?: string
      retryable?: boolean
      replayId?: string
    }
  | {
      type: 'done'
      status: AnalysisStatus
      replayId?: string
    }

export type AnalysisStreamState = {
  status: AnalysisStatus | null
  outputText: string
  reasoningSummaries: string[]
  timeline: AnalysisTimelineItem[]
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
    timeline: [],
    lastReplayId: null,
    isTerminal: false,
    error: null,
  }
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
      timeline: [
        ...state.timeline,
        {
          type: 'status',
          status: event.status,
          replayId: event.replayId,
        },
      ],
    }
  }

  if (event.kind === 'output_delta') {
    return {
      ...state,
      outputText: state.outputText + event.text,
      lastReplayId: nextReplayId,
    }
  }

  if (event.kind === 'reasoning_summary') {
    return {
      ...state,
      reasoningSummaries: [...state.reasoningSummaries, event.text],
      lastReplayId: nextReplayId,
      timeline: [
        ...state.timeline,
        {
          type: 'reasoning_summary',
          text: event.text,
          replayId: event.replayId,
        },
      ],
    }
  }

  if (event.kind === 'tool_call') {
    return {
      ...state,
      lastReplayId: nextReplayId,
      timeline: [
        ...state.timeline,
        {
          type: 'tool_call',
          toolCallId: event.toolCallId,
          toolName: event.toolName,
          arguments: event.arguments,
          replayId: event.replayId,
        },
      ],
    }
  }

  if (event.kind === 'tool_result') {
    return {
      ...state,
      lastReplayId: nextReplayId,
      timeline: [
        ...state.timeline,
        {
          type: 'tool_result',
          toolCallId: event.toolCallId,
          toolName: event.toolName,
          ok: event.ok,
          result: event.result,
          error: event.error,
          replayId: event.replayId,
        },
      ],
    }
  }

  if (event.kind === 'compact') {
    return {
      ...state,
      lastReplayId: nextReplayId,
      timeline: [
        ...state.timeline,
        {
          type: 'compact',
          tokenEstimate: event.tokenEstimate,
          threshold: event.threshold,
          replayId: event.replayId,
        },
      ],
    }
  }

  if (event.kind === 'attempt_failed') {
    return {
      ...state,
      lastReplayId: nextReplayId,
      timeline: [
        ...state.timeline,
        {
          type: 'attempt_failed',
          message: event.message,
          retryable: event.retryable,
          replayId: event.replayId,
        },
      ],
    }
  }

  if (event.kind === 'done') {
    return {
      ...state,
      status: event.status,
      lastReplayId: nextReplayId,
      isTerminal: true,
      timeline: [
        ...state.timeline,
        {
          type: 'done',
          status: event.status,
          replayId: event.replayId,
        },
      ],
    }
  }

  if (event.kind === 'error') {
    return {
      ...state,
      status: 'failed',
      lastReplayId: nextReplayId,
      isTerminal: true,
      error: {
        code: event.code,
        message: event.message,
        retryable: event.retryable,
      },
      timeline: [
        ...state.timeline,
        {
          type: 'error',
          code: event.code,
          message: event.message,
          retryable: event.retryable,
          replayId: event.replayId,
        },
      ],
    }
  }

  return {
    ...state,
    lastReplayId: nextReplayId,
  }
}
