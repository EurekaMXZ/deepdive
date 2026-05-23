import type { AnalysisStatus, AnalysisStreamEvent } from '../domain/analysis.ts'

export type ParsedSseEvent = {
  id?: string
  event: string
  data: unknown
  rawData: string
}

export type SubscribeAnalysisEventsInput = {
  analysisId: string
  baseUrl?: string
  lastEventId?: string | null
  pollIntervalSeconds?: number
  idleTimeoutSeconds?: number
  debugRawLlmEvents?: boolean
  signal?: AbortSignal
  fetch?: typeof fetch
  onEvent(event: AnalysisStreamEvent): void
}

export class SseDecoder {
  private buffer = ''

  push(chunk: string): ParsedSseEvent[] {
    this.buffer += chunk
    const events: ParsedSseEvent[] = []
    let boundary = findFrameBoundary(this.buffer)

    while (boundary >= 0) {
      const frame = this.buffer.slice(0, boundary)
      this.buffer = this.buffer.slice(skipBoundary(this.buffer, boundary))
      const event = parseSseFrame(frame)
      if (event !== null) {
        events.push(event)
      }
      boundary = findFrameBoundary(this.buffer)
    }

    return events
  }
}

export function parseSseEvents(input: string): ParsedSseEvent[] {
  return new SseDecoder().push(input)
}

export function normalizeAnalysisSseEvent(
  event: ParsedSseEvent,
): AnalysisStreamEvent {
  const data = asRecord(event.data)
  const replayId = event.id

  if (event.event === 'status') {
    return {
      kind: 'status',
      status: stringValue(data.status, 'running') as AnalysisStatus,
      replayId,
    }
  }

  if (event.event === 'delta') {
    return {
      kind: 'output_delta',
      text: stringValue(data.text, ''),
      replayId,
    }
  }

  if (event.event === 'response.output_text.delta') {
    return cleanUndefined({
      kind: 'output_delta',
      text: stringValue(data.delta, ''),
      replayId,
    })
  }

  if (event.event === 'model_reasoning_summary') {
    return cleanUndefined({
      kind: 'reasoning_summary',
      text: stringValue(data.text, ''),
      itemId: optionalString(data.item_id),
      responseId: optionalString(data.response_id),
      replayId,
    })
  }

  if (event.event === 'tool_call') {
    return {
      kind: 'tool_call',
      toolCallId: optionalString(data.tool_call_id),
      toolName: stringValue(data.tool_name, 'unknown_tool'),
      arguments: asRecord(data.arguments),
      replayId,
    }
  }

  if (event.event === 'tool_result') {
    return {
      kind: 'tool_result',
      toolCallId: optionalString(data.tool_call_id),
      toolName: optionalString(data.tool_name),
      ok: optionalBoolean(data.ok),
      result: data.result,
      error: data.error,
      resultRef: optionalString(data.result_ref),
      evidenceIds: stringArray(data.evidence_ids),
      truncated: optionalBoolean(data.truncated),
      nextCursor: optionalNullableString(data.next_cursor),
      replayId,
    }
  }

  if (event.event === 'compact') {
    return {
      kind: 'compact',
      tokenEstimate: optionalNumber(data.token_estimate),
      threshold: optionalNumber(data.threshold),
      replayId,
    }
  }

  if (event.event === 'attempt_failed') {
    return {
      kind: 'attempt_failed',
      turnId: optionalString(data.turn_id),
      attempt: optionalNumber(data.attempt),
      errorCode: optionalString(data.error_code),
      message: optionalString(data.message),
      retryable: optionalBoolean(data.retryable),
      supersedesStreamDeltas: optionalBoolean(data.supersedes_stream_deltas),
      replayId,
    }
  }

  if (event.event === 'done') {
    return {
      kind: 'done',
      status: stringValue(data.status, 'completed') as AnalysisStatus,
      responseId: optionalString(data.response_id),
      outputRef: optionalString(data.output_ref),
      replayId,
    }
  }

  if (event.event === 'error' || event.event === 'analysis_error') {
    const error = asRecord(data.error)
    return {
      kind: 'error',
      code: optionalString(error.code) ?? optionalString(data.error_code),
      message: optionalString(error.message) ?? optionalString(data.error_message),
      retryable: optionalBoolean(error.retryable) ?? optionalBoolean(data.retryable),
      replayId,
    }
  }

  return cleanUndefined({
    kind: 'raw',
    event: event.event,
    data: event.data,
    replayId,
  })
}

export async function subscribeAnalysisEvents(
  input: SubscribeAnalysisEventsInput,
): Promise<void> {
  const fetcher = input.fetch ?? fetch.bind(globalThis)
  const response = await fetcher(buildEventsUrl(input), {
    headers: input.lastEventId ? { 'Last-Event-ID': input.lastEventId } : undefined,
    signal: input.signal,
  })
  if (!response.ok) {
    throw new Error(`SSE request failed with HTTP ${response.status}`)
  }
  if (!response.body) {
    throw new Error('SSE response body is not readable.')
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  const decoder = new SseDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      return
    }
    for (const event of decoder.push(value)) {
      input.onEvent(normalizeAnalysisSseEvent(event))
    }
  }
}

function parseSseFrame(frame: string): ParsedSseEvent | null {
  const lines = frame.split(/\r?\n/)
  let id: string | undefined
  let event = 'message'
  const dataLines: string[] = []

  for (const line of lines) {
    if (!line || line.startsWith(':')) {
      continue
    }
    const separator = line.indexOf(':')
    const field = separator >= 0 ? line.slice(0, separator) : line
    const rawValue = separator >= 0 ? line.slice(separator + 1) : ''
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue

    if (field === 'id') {
      id = value
    } else if (field === 'event') {
      event = value
    } else if (field === 'data') {
      dataLines.push(value)
    }
  }

  if (id === undefined && event === 'message' && dataLines.length === 0) {
    return null
  }

  const rawData = dataLines.join('\n')
  return {
    id,
    event,
    data: parseData(rawData),
    rawData,
  }
}

function buildEventsUrl(input: SubscribeAnalysisEventsInput): string {
  const baseUrl = (input.baseUrl ?? '/api').replace(/\/$/, '')
  const path = `/analysis/${encodeURIComponent(input.analysisId)}/events`
  const url = /^https?:\/\//i.test(baseUrl)
    ? new URL(path, `${baseUrl}/`)
    : new URL(`${baseUrl}${path}`, window.location.origin)

  appendOptional(url, 'poll_interval_seconds', input.pollIntervalSeconds)
  appendOptional(url, 'idle_timeout_seconds', input.idleTimeoutSeconds)
  appendOptional(url, 'debug_raw_llm_events', input.debugRawLlmEvents)

  return /^https?:\/\//i.test(baseUrl)
    ? url.toString()
    : `${url.pathname}${url.search}`
}

function parseData(rawData: string): unknown {
  if (!rawData) {
    return null
  }
  try {
    return JSON.parse(rawData)
  } catch {
    return rawData
  }
}

function findFrameBoundary(value: string): number {
  const lf = value.indexOf('\n\n')
  const crlf = value.indexOf('\r\n\r\n')
  if (lf < 0) {
    return crlf
  }
  if (crlf < 0) {
    return lf
  }
  return Math.min(lf, crlf)
}

function skipBoundary(value: string, boundary: number): number {
  return value.startsWith('\r\n\r\n', boundary) ? boundary + 4 : boundary + 2
}

function appendOptional(
  url: URL,
  key: string,
  value: boolean | number | undefined,
): void {
  if (value !== undefined) {
    url.searchParams.set(key, String(value))
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function optionalNullableString(value: unknown): string | null | undefined {
  if (value === null) {
    return null
  }
  return optionalString(value)
}

function optionalBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined
}

function stringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined
  }
  return value.filter((item): item is string => typeof item === 'string')
}

function cleanUndefined<T extends Record<string, unknown>>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== undefined),
  ) as T
}
