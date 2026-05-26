import type {
  Analysis,
  AnalysisCreated,
  AnalysisListPage,
  AnalysisSuggestionListPage,
  CreateAnalysisInput,
  ListAnalysisSuggestionsInput,
  ListAnalysesInput,
} from '../domain/analysis.ts'
import type {
  CreateUserInput,
  LoginInput,
  PermissionListPage,
  RegisterInput,
  RoleListPage,
  TokenPair,
  UpdateUserInput,
  User,
  UserListPage,
  UserRoles,
} from '../domain/auth.ts'
import type {
  DocumentArtifact,
  DocumentArtifactWithContent,
  DocumentListPage,
  DocumentRevisionListPage,
  DocumentTreePage,
} from '../domain/documents.ts'
import {
  type BackendAnalysis,
  type BackendAnalysisCreated,
  type BackendAnalysisListPage,
  type BackendAnalysisSuggestionListPage,
  type BackendDocument,
  type BackendDocumentListPage,
  type BackendDocumentRevisionListPage,
  type BackendDocumentTreePage,
  type BackendDocumentWithContent,
  type BackendErrorResponse,
  type BackendPermissionListPage,
  type BackendRoleListPage,
  type BackendTokenPair,
  type BackendUser,
  type BackendUserListPage,
  type BackendUserRoles,
  fromBackendAnalysis,
  fromBackendAnalysisCreated,
  fromBackendAnalysisListPage,
  fromBackendAnalysisSuggestionListPage,
  fromBackendDocument,
  fromBackendDocumentListPage,
  fromBackendDocumentRevisionListPage,
  fromBackendDocumentTreePage,
  fromBackendDocumentWithContent,
  fromBackendPermissionListPage,
  fromBackendRoleListPage,
  fromBackendTokenPair,
  fromBackendUser,
  fromBackendUserListPage,
  fromBackendUserRoles,
} from './wire.ts'

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>

export type DeepDiveApiClientOptions = {
  accessToken?: string | (() => string | null | undefined)
  baseUrl?: string
  fetch?: FetchLike
}

export type DeepDiveApiClient = {
  register(input: RegisterInput): Promise<User>
  login(input: LoginInput): Promise<TokenPair>
  refreshToken(refreshToken: string): Promise<TokenPair>
  logout(refreshToken: string): Promise<void>
  getCurrentUser(): Promise<User>
  createAnalysis(input: CreateAnalysisInput): Promise<AnalysisCreated>
  listAnalyses(input?: ListAnalysesInput): Promise<AnalysisListPage>
  listAnalysisSuggestions(input: ListAnalysisSuggestionsInput): Promise<AnalysisSuggestionListPage>
  getAnalysis(analysisId: string): Promise<Analysis>
  cancelAnalysis(analysisId: string): Promise<Analysis>
  listUsers(): Promise<UserListPage>
  createUser(input: CreateUserInput): Promise<User>
  getUser(userId: string): Promise<User>
  updateUser(userId: string, input: UpdateUserInput): Promise<User>
  updateUserRoles(userId: string, roleIds: string[]): Promise<UserRoles>
  listRoles(): Promise<RoleListPage>
  listPermissions(): Promise<PermissionListPage>
  listAnalysisDocuments(analysisId: string): Promise<DocumentListPage>
  getAnalysisDocumentsTree(analysisId: string): Promise<DocumentTreePage>
  getAnalysisDocument(analysisId: string, documentId: string): Promise<DocumentArtifact>
  getAnalysisDocumentContent(
    analysisId: string,
    documentId: string,
  ): Promise<DocumentArtifactWithContent>
  listAnalysisDocumentRevisions(
    analysisId: string,
    documentId: string,
  ): Promise<DocumentRevisionListPage>
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
  const request = <T>(path: string, init?: RequestInit) =>
    requestJson<T>(fetcher, urlFor(baseUrl, path), withAuth(init, options.accessToken))

  return {
    async register(input) {
      const value = await request<BackendUser>('/auth/register', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          email: input.email,
          password: input.password,
          display_name: input.displayName,
        }),
      })
      return fromBackendUser(value)
    },

    async login(input) {
      const value = await request<BackendTokenPair>('/auth/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          email: input.email,
          password: input.password,
          turnstile_token: input.turnstileToken,
        }),
      })
      return fromBackendTokenPair(value)
    },

    async refreshToken(refreshToken) {
      const value = await request<BackendTokenPair>('/auth/refresh', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      return fromBackendTokenPair(value)
    },

    async logout(refreshToken) {
      await request<void>('/auth/logout', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
    },

    async getCurrentUser() {
      const value = await request<BackendUser>('/auth/me')
      return fromBackendUser(value)
    },

    async createAnalysis(input) {
      const body = {
        repository_url: input.repositoryUrl,
        ref: input.ref,
      }
      const value = await request<BackendAnalysisCreated>('/analysis', {
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
      const value = await requestJson<BackendAnalysisListPage>(
        fetcher,
        url,
        withAuth(undefined, options.accessToken),
      )
      return fromBackendAnalysisListPage(value)
    },

    async listAnalysisSuggestions(input) {
      const url = withSearchParams(urlFor(baseUrl, '/repositories/search'), {
        q: input.repositoryQuery,
        limit: input.limit,
      })
      const value = await requestJson<BackendAnalysisSuggestionListPage>(
        fetcher,
        url,
        withAuth(undefined, options.accessToken),
      )
      return fromBackendAnalysisSuggestionListPage(value)
    },

    async getAnalysis(analysisId) {
      const value = await request<BackendAnalysis>(`/analysis/${encodeURIComponent(analysisId)}`)
      return fromBackendAnalysis(value)
    },

    async cancelAnalysis(analysisId) {
      const value = await request<BackendAnalysis>(
        `/analysis/${encodeURIComponent(analysisId)}/cancel`,
        { method: 'POST' },
      )
      return fromBackendAnalysis(value)
    },

    async listUsers() {
      const value = await request<BackendUserListPage>('/users')
      return fromBackendUserListPage(value)
    },

    async createUser(input) {
      const value = await request<BackendUser>('/users', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          email: input.email,
          password: input.password,
          display_name: input.displayName,
          role_names: input.roleNames,
        }),
      })
      return fromBackendUser(value)
    },

    async getUser(userId) {
      const value = await request<BackendUser>(`/users/${encodeURIComponent(userId)}`)
      return fromBackendUser(value)
    },

    async updateUser(userId, input) {
      const value = await request<BackendUser>(`/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          display_name: input.displayName,
          is_active: input.isActive,
        }),
      })
      return fromBackendUser(value)
    },

    async updateUserRoles(userId, roleIds) {
      const value = await request<BackendUserRoles>(`/users/${encodeURIComponent(userId)}/roles`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ role_ids: roleIds }),
      })
      return fromBackendUserRoles(value)
    },

    async listRoles() {
      const value = await request<BackendRoleListPage>('/roles')
      return fromBackendRoleListPage(value)
    },

    async listPermissions() {
      const value = await request<BackendPermissionListPage>('/permissions')
      return fromBackendPermissionListPage(value)
    },

    async listAnalysisDocuments(analysisId) {
      const value = await request<BackendDocumentListPage>(
        `/analysis/${encodeURIComponent(analysisId)}/documents`,
      )
      return fromBackendDocumentListPage(value)
    },

    async getAnalysisDocumentsTree(analysisId) {
      const value = await request<BackendDocumentTreePage>(
        `/analysis/${encodeURIComponent(analysisId)}/documents/tree`,
      )
      return fromBackendDocumentTreePage(value)
    },

    async getAnalysisDocument(analysisId, documentId) {
      const value = await request<BackendDocument>(
        `/analysis/${encodeURIComponent(analysisId)}/documents/${encodeURIComponent(documentId)}`,
      )
      return fromBackendDocument(value)
    },

    async getAnalysisDocumentContent(analysisId, documentId) {
      const value = await request<BackendDocumentWithContent>(
        `/analysis/${encodeURIComponent(analysisId)}/documents/${encodeURIComponent(documentId)}/content`,
      )
      return fromBackendDocumentWithContent(value)
    },

    async listAnalysisDocumentRevisions(analysisId, documentId) {
      const value = await request<BackendDocumentRevisionListPage>(
        `/analysis/${encodeURIComponent(analysisId)}/documents/${encodeURIComponent(documentId)}/revisions`,
      )
      return fromBackendDocumentRevisionListPage(value)
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

function withAuth(
  init: RequestInit | undefined,
  accessToken: DeepDiveApiClientOptions['accessToken'],
): RequestInit {
  const token = resolveAccessToken(accessToken)
  if (!token) {
    return init ?? {}
  }
  return {
    ...init,
    headers: {
      ...init?.headers,
      authorization: `Bearer ${token}`,
    },
  }
}

function resolveAccessToken(
  accessToken: DeepDiveApiClientOptions['accessToken'],
): string | null | undefined {
  return typeof accessToken === 'function' ? accessToken() : accessToken
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
