import type {
  Analysis,
  AnalysisId,
  AnalysisPhase,
  AnalysisStatus,
  AnalysisSuggestion,
} from './analysis.ts'
import { getAnalysisStatusMeta } from './analysis.ts'
import { normalizeRepositoryQuery } from './projectSearch.ts'

export type CreateAnalysisDraft = {
  repository: string
  ref: string
}

export type NormalizedCreateAnalysisDraft = {
  repositoryUrl: string
  ref: string
}

export type CreateAnalysisDraftValidation = {
  canSubmit: boolean
  repositoryError: string | null
}

export type AnalysisSubmissionRow = {
  analysisId: AnalysisId
  analysisHref: string
  canCancel: boolean
  documentsHref: string | null
  repositoryLabel: string
  repositoryUrl: string
  requestedRef: string
  status: AnalysisStatus
  statusLabel: string
  statusPhase: AnalysisPhase
  updatedAt: string
  updatedAtLabel: string
}

export function createAnalysisSubmissionRows(
  analyses: Analysis[],
): AnalysisSubmissionRow[] {
  return [...analyses]
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .map((analysis) => {
      const statusMeta = getAnalysisStatusMeta(analysis.status)
      return {
        analysisId: analysis.analysisId,
        analysisHref: analysisHref(analysis.analysisId),
        canCancel: canCancelAnalysisStatus(analysis.status),
        documentsHref: documentHrefForStatus(analysis.analysisId, analysis.status),
        repositoryLabel: repositoryLabelFromUrl(analysis.repositoryUrl),
        repositoryUrl: analysis.repositoryUrl,
        requestedRef: analysis.requestedRef,
        status: analysis.status,
        statusLabel: statusMeta.label,
        statusPhase: statusMeta.phase,
        updatedAt: analysis.updatedAt,
        updatedAtLabel: formatUtcDateTime(analysis.updatedAt),
      }
    })
}

export function canCancelAnalysisStatus(status: AnalysisStatus): boolean {
  return !getAnalysisStatusMeta(status).terminal && status !== 'cancelling'
}

export function documentHrefForAnalysisRow(row: AnalysisSubmissionRow): string | null {
  return row.documentsHref
}

export function documentHrefForAnalysisSuggestion(
  suggestion: AnalysisSuggestion,
): string | null {
  return documentHrefForStatus(suggestion.analysisId, suggestion.status)
}

export function normalizeCreateAnalysisDraft(
  draft: CreateAnalysisDraft,
): NormalizedCreateAnalysisDraft {
  return {
    repositoryUrl: normalizeRepositoryQuery(draft.repository),
    ref: draft.ref.trim() || 'main',
  }
}

export function validateCreateAnalysisDraft(
  draft: CreateAnalysisDraft,
): CreateAnalysisDraftValidation {
  const repository = draft.repository.trim()
  return {
    canSubmit: repository.length > 0,
    repositoryError: repository.length > 0 ? null : '请输入仓库地址',
  }
}

function repositoryLabelFromUrl(repositoryUrl: string): string {
  try {
    const url = new URL(repositoryUrl)
    if (url.hostname === 'github.com') {
      const path = url.pathname.replace(/^\/+|\/+$/g, '').replace(/\.git$/, '')
      if (path.split('/').length === 2) {
        return path
      }
    }
  } catch {
    return repositoryUrl
  }
  return repositoryUrl
}

function analysisHref(analysisId: string): string {
  return `/analysis/${encodeURIComponent(analysisId)}`
}

function documentHrefForStatus(
  analysisId: string,
  status: AnalysisStatus,
): string | null {
  return getAnalysisStatusMeta(status).terminal && status !== 'failed' && status !== 'cancelled'
    ? `${analysisHref(analysisId)}/documents`
    : null
}

function formatUtcDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  const year = date.getUTCFullYear()
  const month = String(date.getUTCMonth() + 1).padStart(2, '0')
  const day = String(date.getUTCDate()).padStart(2, '0')
  const hour = String(date.getUTCHours()).padStart(2, '0')
  const minute = String(date.getUTCMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hour}:${minute}`
}
