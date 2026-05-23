import type {
  Analysis,
  AnalysisCreated,
  AnalysisListPage,
  AnalysisStatus,
} from '../domain/analysis.ts'

export type BackendAnalysis = {
  analysis_id: string
  agent_id: string
  snapshot_id: string | null
  status: AnalysisStatus
  repository_url: string
  requested_ref: string
  resolved_commit_sha: string | null
  error_code?: string | null
  error_message?: string | null
  created_at: string
  updated_at: string
}

export type BackendAnalysisCreated = {
  analysis_id: string
  agent_id: string
  snapshot_id: string | null
  status: AnalysisStatus
  created_at: string
}

export type BackendAnalysisListPage = {
  items: BackendAnalysis[]
  next_cursor: string | null
}

export type BackendErrorResponse = {
  error?: {
    code?: string
    message?: string
    request_id?: string
    retryable?: boolean
  }
}

export function fromBackendAnalysis(value: BackendAnalysis): Analysis {
  return {
    analysisId: value.analysis_id,
    agentId: value.agent_id,
    snapshotId: value.snapshot_id,
    status: value.status,
    repositoryUrl: value.repository_url,
    requestedRef: value.requested_ref,
    resolvedCommitSha: value.resolved_commit_sha,
    errorCode: value.error_code ?? null,
    errorMessage: value.error_message ?? null,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  }
}

export function fromBackendAnalysisCreated(
  value: BackendAnalysisCreated,
): AnalysisCreated {
  return {
    analysisId: value.analysis_id,
    agentId: value.agent_id,
    snapshotId: value.snapshot_id,
    status: value.status,
    createdAt: value.created_at,
  }
}

export function fromBackendAnalysisListPage(
  value: BackendAnalysisListPage,
): AnalysisListPage {
  return {
    items: value.items.map(fromBackendAnalysis),
    nextCursor: value.next_cursor ?? null,
  }
}
