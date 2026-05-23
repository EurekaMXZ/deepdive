import type {
  Analysis,
  AnalysisCreated,
  AnalysisListPage,
  CreateAnalysisInput,
  ListAnalysesInput,
} from '../domain/analysis.ts'
import {
  type BackendAnalysis,
  type BackendAnalysisCreated,
  type BackendAnalysisListPage,
  type BackendErrorResponse,
  fromBackendAnalysis,
  fromBackendAnalysisCreated,
  fromBackendAnalysisListPage,
} from './wire.ts'

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>

export type DeepDiveApiClientOptions = {
  baseUrl?: string
  fetch?: FetchLike
}

export type DeepDiveApiClient = {
  createAnalysis(input: CreateAnalysisInput): Promise<AnalysisCreated>
  listAnalyses(input?: ListAnalysesInput): Promise<AnalysisListPage>
  getAnalysis(analysisId: string): Promise<Analysis>
  cancelAnalysis(analysisId: string): Promise<Analysis>
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId?: string
  readonly retryable?: boolean

  constructor(params: {
    status: number
    code: string
    message: string
    requestId?: string
    retryable?: boolean
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.status = params.status
    this.code = params.code
    this.requestId = params.requestId
    this.retryable = params.retryable
  }
}

export function createDeepDiveApiClient(
  options: DeepDiveApiClientOptions = {},
): DeepDiveApiClient {
  const baseUrl = normalizeBaseUrl(options.baseUrl ?? '/api')
  const fetcher = options.fetch ?? fetch.bind(globalThis)

  return {
    async createAnalysis(input) {
      const body = {
        repository_url: input.repositoryUrl,
        ref: input.ref,
      }
      const value = await requestJson<BackendAnalysisCreated>(fetcher, urlFor(baseUrl, '/analysis'), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      return fromBackendAnalysisCreated(value)
    },

    async listAnalyses(input = {}) {
      const url = withSearchParams(urlFor(baseUrl, '/analysis'), {
        status: input.status,
        repository_url_hash: input.repositoryUrlHash,
        created_after: input.createdAfter,
        created_before: input.createdBefore,
        limit: input.limit,
        cursor: input.cursor,
      })
      const value = await requestJson<BackendAnalysisListPage>(fetcher, url)
      return fromBackendAnalysisListPage(value)
    },

    async getAnalysis(analysisId) {
      const value = await requestJson<BackendAnalysis>(
        fetcher,
        urlFor(baseUrl, `/analysis/${encodeURIComponent(analysisId)}`),
      )
      return fromBackendAnalysis(value)
    },

    async cancelAnalysis(analysisId) {
      const value = await requestJson<BackendAnalysis>(
        fetcher,
        urlFor(baseUrl, `/analysis/${encodeURIComponent(analysisId)}/cancel`),
        { method: 'POST' },
      )
      return fromBackendAnalysis(value)
    },
  }
}

async function requestJson<T>(
  fetcher: FetchLike,
  url: URL | string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetcher(url instanceof URL ? String(url) : url, {
    ...init,
    headers: {
      accept: 'application/json',
      ...init?.headers,
    },
  })
  const payload = await readJson(response)
  if (!response.ok) {
    throw apiErrorFromResponse(response, payload)
  }
  return payload as T
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) {
    return null
  }
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function apiErrorFromResponse(response: Response, payload: unknown): ApiError {
  const body = isRecord(payload) ? (payload as BackendErrorResponse) : {}
  const error = body.error ?? {}
  return new ApiError({
    status: response.status,
    code: error.code ?? `HTTP_${response.status}`,
    message: error.message ?? response.statusText,
    requestId: error.request_id,
    retryable: error.retryable,
  })
}

function withSearchParams(
  url: URL | string,
  params: Record<string, string | number | undefined>,
): URL | string {
  if (url instanceof URL) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }
    return url
  }
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') {
      search.set(key, String(value))
    }
  }
  const query = search.toString()
  return query ? `${url}?${query}` : url
}

function normalizeBaseUrl(value: string): string {
  return value.endsWith('/') ? value.slice(0, -1) : value
}

function urlFor(baseUrl: string, path: string): URL | string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  if (isAbsoluteUrl(baseUrl)) {
    return new URL(normalizedPath, `${baseUrl}/`)
  }
  const joined = `${baseUrl}${normalizedPath}`
  return joined.replace(/\/{2,}/g, '/')
}

function isAbsoluteUrl(value: string): boolean {
  return /^https?:\/\//i.test(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
