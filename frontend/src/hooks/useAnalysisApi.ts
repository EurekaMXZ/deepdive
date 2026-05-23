import { useCallback, useEffect, useMemo, useState } from 'react'

import { createDeepDiveApiClient, type DeepDiveApiClient } from '../api/client.ts'
import {
  applyAnalysisStreamEvent,
  createInitialAnalysisStreamState,
  type Analysis,
  type AnalysisCreated,
  type AnalysisId,
  type AnalysisListPage,
  type AnalysisStreamState,
  type CreateAnalysisInput,
  type ListAnalysesInput,
} from '../domain/analysis.ts'
import { subscribeAnalysisEvents } from '../api/sse.ts'

export type AsyncState<T> = {
  data: T | null
  loading: boolean
  error: Error | null
}

export type UseAnalysisApiOptions = {
  client?: DeepDiveApiClient
  baseUrl?: string
}

export type UseAnalysisEventsOptions = {
  analysisId: AnalysisId | null
  baseUrl?: string
  enabled?: boolean
  lastEventId?: string | null
  debugRawLlmEvents?: boolean
}

type KeyedAnalysisStreamState = {
  key: string
  stream: AnalysisStreamState
}

export function useAnalysisClient(options: UseAnalysisApiOptions = {}): DeepDiveApiClient {
  return useMemo(
    () => options.client ?? createDeepDiveApiClient({ baseUrl: options.baseUrl }),
    [options.baseUrl, options.client],
  )
}

export function useCreateAnalysis(options: UseAnalysisApiOptions = {}) {
  const client = useAnalysisClient(options)
  const [state, setState] = useState<AsyncState<AnalysisCreated>>({
    data: null,
    loading: false,
    error: null,
  })

  const createAnalysis = useCallback(
    async (input: CreateAnalysisInput) => {
      setState({ data: null, loading: true, error: null })
      try {
        const data = await client.createAnalysis(input)
        setState({ data, loading: false, error: null })
        return data
      } catch (error) {
        const normalized = normalizeError(error)
        setState({ data: null, loading: false, error: normalized })
        throw normalized
      }
    },
    [client],
  )

  return {
    ...state,
    createAnalysis,
  }
}

export function useAnalysisList(options: UseAnalysisApiOptions = {}) {
  const client = useAnalysisClient(options)
  const [state, setState] = useState<AsyncState<AnalysisListPage>>({
    data: null,
    loading: false,
    error: null,
  })

  const loadAnalyses = useCallback(
    async (input?: ListAnalysesInput) => {
      setState((current) => ({ ...current, loading: true, error: null }))
      try {
        const data = await client.listAnalyses(input)
        setState({ data, loading: false, error: null })
        return data
      } catch (error) {
        const normalized = normalizeError(error)
        setState((current) => ({ ...current, loading: false, error: normalized }))
        throw normalized
      }
    },
    [client],
  )

  return {
    ...state,
    loadAnalyses,
  }
}

export function useAnalysisDetail(options: UseAnalysisApiOptions = {}) {
  const client = useAnalysisClient(options)
  const [state, setState] = useState<AsyncState<Analysis>>({
    data: null,
    loading: false,
    error: null,
  })

  const loadAnalysis = useCallback(
    async (analysisId: AnalysisId) => {
      setState((current) => ({ ...current, loading: true, error: null }))
      try {
        const data = await client.getAnalysis(analysisId)
        setState({ data, loading: false, error: null })
        return data
      } catch (error) {
        const normalized = normalizeError(error)
        setState((current) => ({ ...current, loading: false, error: normalized }))
        throw normalized
      }
    },
    [client],
  )

  const cancelAnalysis = useCallback(
    async (analysisId: AnalysisId) => {
      setState((current) => ({ ...current, loading: true, error: null }))
      try {
        const data = await client.cancelAnalysis(analysisId)
        setState({ data, loading: false, error: null })
        return data
      } catch (error) {
        const normalized = normalizeError(error)
        setState((current) => ({ ...current, loading: false, error: normalized }))
        throw normalized
      }
    },
    [client],
  )

  return {
    ...state,
    loadAnalysis,
    cancelAnalysis,
  }
}

export function useAnalysisEvents(options: UseAnalysisEventsOptions): AnalysisStreamState {
  const streamKey = [
    options.analysisId ?? '',
    options.lastEventId ?? '',
    options.debugRawLlmEvents ? 'debug' : 'default',
  ].join('|')
  const [state, setState] = useState<KeyedAnalysisStreamState>(() => ({
    key: streamKey,
    stream: createInitialAnalysisStreamState(),
  }))
  const visibleState = state.key === streamKey ? state.stream : createInitialAnalysisStreamState()

  useEffect(() => {
    const enabled = options.enabled ?? true
    if (!enabled || !options.analysisId) {
      return
    }

    const controller = new AbortController()

    void subscribeAnalysisEvents({
      analysisId: options.analysisId,
      baseUrl: options.baseUrl,
      lastEventId: options.lastEventId,
      debugRawLlmEvents: options.debugRawLlmEvents,
      signal: controller.signal,
      onEvent: (event) => {
        setState((current) => ({
          key: streamKey,
          stream: applyAnalysisStreamEvent(
            current.key === streamKey ? current.stream : createInitialAnalysisStreamState(),
            event,
          ),
        }))
      },
    }).catch((error) => {
      if (!controller.signal.aborted) {
        const normalized = normalizeError(error)
        setState((current) => ({
          key: streamKey,
          stream: applyAnalysisStreamEvent(
            current.key === streamKey ? current.stream : createInitialAnalysisStreamState(),
            {
              kind: 'error',
              message: normalized.message,
            },
          ),
        }))
      }
    })

    return () => controller.abort()
  }, [
    options.analysisId,
    options.baseUrl,
    options.debugRawLlmEvents,
    options.enabled,
    options.lastEventId,
    streamKey,
  ])

  return visibleState
}

function normalizeError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error))
}
