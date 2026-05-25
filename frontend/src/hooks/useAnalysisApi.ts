import { useCallback, useEffect, useMemo, useState } from 'react'

import { createDeepDiveApiClient, type DeepDiveApiClient } from '../api/client.ts'
import {
  applyAnalysisStreamEvent,
  createInitialAnalysisStreamState,
  type Analysis,
  type AnalysisCreated,
  type AnalysisId,
  type AnalysisListPage,
  type AnalysisSuggestionListPage,
  type AnalysisStreamState,
  type CreateAnalysisInput,
  type ListAnalysisSuggestionsInput,
  type ListAnalysesInput,
} from '../domain/analysis.ts'
import type {
  CreateUserInput,
  LoginInput,
  RegisterInput,
  TokenPair,
  UpdateUserInput,
  User,
  UserListPage,
  RoleListPage,
  PermissionListPage,
  UserRoles,
} from '../domain/auth.ts'
import type {
  DocumentArtifact,
  DocumentArtifactWithContent,
  DocumentListPage,
  DocumentRevisionListPage,
} from '../domain/documents.ts'
import { subscribeAnalysisEvents } from '../api/sse.ts'

export type AsyncState<T> = {
  data: T | null
  loading: boolean
  error: Error | null
}

export type UseAnalysisApiOptions = {
  accessToken?: string | (() => string | null | undefined)
  client?: DeepDiveApiClient
  baseUrl?: string
}

export type UseAnalysisEventsOptions = {
  accessToken?: string | (() => string | null | undefined)
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
    () =>
      options.client ??
      createDeepDiveApiClient({
        accessToken: options.accessToken,
        baseUrl: options.baseUrl,
      }),
    [options.accessToken, options.baseUrl, options.client],
  )
}

export function useAuthApi(options: UseAnalysisApiOptions = {}) {
  const client = useAnalysisClient(options)
  const [userState, setUserState] = useState<AsyncState<User>>({
    data: null,
    loading: false,
    error: null,
  })
  const [tokenState, setTokenState] = useState<AsyncState<TokenPair>>({
    data: null,
    loading: false,
    error: null,
  })

  const register = useCallback(
    async (input: RegisterInput) => runAsync(setUserState, () => client.register(input)),
    [client],
  )
  const login = useCallback(
    async (input: LoginInput) => runAsync(setTokenState, () => client.login(input)),
    [client],
  )
  const refreshToken = useCallback(
    async (refreshTokenValue: string) =>
      runAsync(setTokenState, () => client.refreshToken(refreshTokenValue)),
    [client],
  )
  const logout = useCallback(
    async (refreshTokenValue: string) => client.logout(refreshTokenValue),
    [client],
  )
  const loadCurrentUser = useCallback(
    async () => runAsync(setUserState, () => client.getCurrentUser()),
    [client],
  )

  return {
    user: userState.data,
    userLoading: userState.loading,
    userError: userState.error,
    tokens: tokenState.data,
    tokenLoading: tokenState.loading,
    tokenError: tokenState.error,
    register,
    login,
    refreshToken,
    logout,
    loadCurrentUser,
  }
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

export function useUserManagementApi(options: UseAnalysisApiOptions = {}) {
  const client = useAnalysisClient(options)
  const [usersState, setUsersState] = useState<AsyncState<UserListPage>>({
    data: null,
    loading: false,
    error: null,
  })
  const [rolesState, setRolesState] = useState<AsyncState<RoleListPage>>({
    data: null,
    loading: false,
    error: null,
  })
  const [permissionsState, setPermissionsState] = useState<AsyncState<PermissionListPage>>({
    data: null,
    loading: false,
    error: null,
  })
  const [selectedUserState, setSelectedUserState] = useState<AsyncState<User>>({
    data: null,
    loading: false,
    error: null,
  })
  const [userRolesState, setUserRolesState] = useState<AsyncState<UserRoles>>({
    data: null,
    loading: false,
    error: null,
  })

  return {
    users: usersState,
    roles: rolesState,
    permissions: permissionsState,
    selectedUser: selectedUserState,
    userRoles: userRolesState,
    loadUsers: useCallback(() => runAsync(setUsersState, () => client.listUsers()), [client]),
    createUser: useCallback(
      (input: CreateUserInput) => runAsync(setSelectedUserState, () => client.createUser(input)),
      [client],
    ),
    loadUser: useCallback(
      (userId: string) => runAsync(setSelectedUserState, () => client.getUser(userId)),
      [client],
    ),
    updateUser: useCallback(
      (userId: string, input: UpdateUserInput) =>
        runAsync(setSelectedUserState, () => client.updateUser(userId, input)),
      [client],
    ),
    updateUserRoles: useCallback(
      (userId: string, roleIds: string[]) =>
        runAsync(setUserRolesState, () => client.updateUserRoles(userId, roleIds)),
      [client],
    ),
    loadRoles: useCallback(() => runAsync(setRolesState, () => client.listRoles()), [client]),
    loadPermissions: useCallback(
      () => runAsync(setPermissionsState, () => client.listPermissions()),
      [client],
    ),
  }
}

export function useAnalysisDocumentsApi(options: UseAnalysisApiOptions = {}) {
  const client = useAnalysisClient(options)
  const [documentsState, setDocumentsState] = useState<AsyncState<DocumentListPage>>({
    data: null,
    loading: false,
    error: null,
  })
  const [documentState, setDocumentState] = useState<AsyncState<DocumentArtifact>>({
    data: null,
    loading: false,
    error: null,
  })
  const [contentState, setContentState] = useState<AsyncState<DocumentArtifactWithContent>>({
    data: null,
    loading: false,
    error: null,
  })
  const [revisionsState, setRevisionsState] = useState<AsyncState<DocumentRevisionListPage>>({
    data: null,
    loading: false,
    error: null,
  })

  return {
    documents: documentsState,
    document: documentState,
    content: contentState,
    revisions: revisionsState,
    loadDocuments: useCallback(
      (analysisId: AnalysisId) =>
        runAsync(setDocumentsState, () => client.listAnalysisDocuments(analysisId)),
      [client],
    ),
    loadDocument: useCallback(
      (analysisId: AnalysisId, documentId: string) =>
        runAsync(setDocumentState, () => client.getAnalysisDocument(analysisId, documentId)),
      [client],
    ),
    loadDocumentContent: useCallback(
      (analysisId: AnalysisId, documentId: string) =>
        runAsync(setContentState, () => client.getAnalysisDocumentContent(analysisId, documentId)),
      [client],
    ),
    loadDocumentRevisions: useCallback(
      (analysisId: AnalysisId, documentId: string) =>
        runAsync(setRevisionsState, () =>
          client.listAnalysisDocumentRevisions(analysisId, documentId),
        ),
      [client],
    ),
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

export function useAnalysisSuggestions(options: UseAnalysisApiOptions = {}) {
  const client = useAnalysisClient(options)
  const [state, setState] = useState<AsyncState<AnalysisSuggestionListPage>>({
    data: null,
    loading: false,
    error: null,
  })

  const loadSuggestions = useCallback(
    async (input: ListAnalysisSuggestionsInput) =>
      runAsync(setState, () => client.listAnalysisSuggestions(input)),
    [client],
  )

  return {
    ...state,
    loadSuggestions,
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
      accessToken: options.accessToken,
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
    options.accessToken,
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

async function runAsync<T>(
  setState: React.Dispatch<React.SetStateAction<AsyncState<T>>>,
  run: () => Promise<T>,
): Promise<T> {
  setState((current) => ({ ...current, loading: true, error: null }))
  try {
    const data = await run()
    setState({ data, loading: false, error: null })
    return data
  } catch (error) {
    const normalized = normalizeError(error)
    setState((current) => ({ ...current, loading: false, error: normalized }))
    throw normalized
  }
}
