import { Plus, XCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import { WorkspaceTopbar } from '../../components/WorkspaceTopbar'
import {
  createAnalysisSubmissionRows,
  type NormalizedCreateAnalysisDraft,
} from '../../domain'
import { useAnalysisClient, useAnalysisList, useCreateAnalysis } from '../../hooks'
import { AnalysisList } from './AnalysisList'
import { CreateAnalysisDialog } from './CreateAnalysisDialog'

type AnalysisSubmissionsPageProps = {
  accessToken?: string | (() => string | null | undefined)
  apiBaseUrl?: string
}

const LIST_LIMIT = 50

export function AnalysisSubmissionsPage({
  accessToken,
  apiBaseUrl,
}: AnalysisSubmissionsPageProps) {
  const navigate = useNavigate()
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [createDialogError, setCreateDialogError] = useState<Error | null>(null)
  const [cancelError, setCancelError] = useState<Error | null>(null)
  const [cancellingAnalysisIds, setCancellingAnalysisIds] = useState<Set<string>>(() => new Set())
  const [selectedAnalysisIds, setSelectedAnalysisIds] = useState<Set<string>>(() => new Set())
  const analysisClient = useAnalysisClient({ accessToken, baseUrl: apiBaseUrl })
  const analysisListState = useAnalysisList({ accessToken, baseUrl: apiBaseUrl })
  const createAnalysisState = useCreateAnalysis({ accessToken, baseUrl: apiBaseUrl })
  const { loadAnalyses } = analysisListState
  const rows = useMemo(
    () => createAnalysisSubmissionRows(analysisListState.data?.items ?? []),
    [analysisListState.data?.items],
  )
  const selectedVisibleAnalysisIds = useMemo(() => {
    const rowIds = new Set(rows.map((row) => row.analysisId))
    return new Set([...selectedAnalysisIds].filter((analysisId) => rowIds.has(analysisId)))
  }, [rows, selectedAnalysisIds])
  const selectedCancellableAnalysisIds = useMemo(
    () =>
      rows
        .filter(
          (row) =>
            row.canCancel &&
            selectedVisibleAnalysisIds.has(row.analysisId) &&
            !cancellingAnalysisIds.has(row.analysisId),
        )
        .map((row) => row.analysisId),
    [cancellingAnalysisIds, rows, selectedVisibleAnalysisIds],
  )

  useEffect(() => {
    void loadAnalyses({ limit: LIST_LIMIT }).catch(() => undefined)
  }, [loadAnalyses])

  async function handleCreateAnalysis(draft: NormalizedCreateAnalysisDraft) {
    setCreateDialogError(null)
    try {
      const created = await createAnalysisState.createAnalysis({
        repositoryUrl: draft.repositoryUrl,
        ref: draft.ref,
      })
      setIsCreateDialogOpen(false)
      navigate(`/analysis/${encodeURIComponent(created.analysisId)}`)
      void loadAnalyses({ limit: LIST_LIMIT }).catch(() => undefined)
    } catch (error) {
      setCreateDialogError(error instanceof Error ? error : new Error(String(error)))
    }
  }

  function handleToggleRowSelection(analysisId: string, selected: boolean) {
    setSelectedAnalysisIds((current) => {
      const next = new Set(current)
      if (selected) {
        next.add(analysisId)
      } else {
        next.delete(analysisId)
      }
      return next
    })
  }

  function handleToggleAllSelection(selected: boolean) {
    setSelectedAnalysisIds((current) => {
      const next = new Set(current)
      for (const row of rows) {
        if (!row.canCancel || cancellingAnalysisIds.has(row.analysisId)) {
          continue
        }
        if (selected) {
          next.add(row.analysisId)
        } else {
          next.delete(row.analysisId)
        }
      }
      return next
    })
  }

  async function handleCancelAnalysis(analysisId: string) {
    const row = rows.find((candidate) => candidate.analysisId === analysisId)
    if (!row?.canCancel || cancellingAnalysisIds.has(analysisId)) {
      return
    }

    setCancelError(null)
    setCancellingAnalysisIds((current) => new Set(current).add(analysisId))
    try {
      await analysisClient.cancelAnalysis(analysisId)
      setSelectedAnalysisIds((current) => {
        const next = new Set(current)
        next.delete(analysisId)
        return next
      })
      void loadAnalyses({ limit: LIST_LIMIT }).catch(() => undefined)
    } catch (error) {
      setCancelError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      setCancellingAnalysisIds((current) => {
        const next = new Set(current)
        next.delete(analysisId)
        return next
      })
    }
  }

  async function handleCancelSelectedAnalyses() {
    if (selectedCancellableAnalysisIds.length === 0) {
      return
    }

    const targetIds = selectedCancellableAnalysisIds
    setCancelError(null)
    setCancellingAnalysisIds((current) => new Set([...current, ...targetIds]))
    const results = await Promise.allSettled(
      targetIds.map((analysisId) => analysisClient.cancelAnalysis(analysisId)),
    )
    const failedCount = results.filter((result) => result.status === 'rejected').length
    setCancellingAnalysisIds((current) => {
      const next = new Set(current)
      for (const analysisId of targetIds) {
        next.delete(analysisId)
      }
      return next
    })
    setSelectedAnalysisIds((current) => {
      const next = new Set(current)
      for (const analysisId of targetIds) {
        next.delete(analysisId)
      }
      return next
    })

    if (failedCount > 0) {
      setCancelError(new Error(`${failedCount} 个任务取消失败`))
    }
    void loadAnalyses({ limit: LIST_LIMIT }).catch(() => undefined)
  }

  function handleCreateDialogOpenChange(open: boolean) {
    setIsCreateDialogOpen(open)
    if (open) {
      setCreateDialogError(null)
    }
  }

  return (
    <main className="workspace workspace--analysis-submissions" aria-labelledby="analysis-submissions-title">
      <WorkspaceTopbar title="提交分析" />
      <section className="workspace-body">
        <h2 className="sr-only" id="analysis-submissions-title">
          提交分析任务列表
        </h2>
        <div className="analysis-submissions">
          <div className="analysis-submissions__toolbar">
            <div className="analysis-submissions__selection">
              <span>已选 {selectedVisibleAnalysisIds.size} 项</span>
              <button
                className="analysis-bulk-cancel-button"
                disabled={selectedCancellableAnalysisIds.length === 0}
                onClick={handleCancelSelectedAnalyses}
                type="button"
              >
                <XCircle size={16} aria-hidden="true" />
                <span>取消选中任务</span>
              </button>
            </div>
            <div className="analysis-submissions__actions">
              <button
                className="analysis-submit-button"
                type="button"
                onClick={() => handleCreateDialogOpenChange(true)}
              >
                <Plus size={17} aria-hidden="true" />
                <span>提交新的任务</span>
              </button>
            </div>
          </div>
          {cancelError ? (
            <div className="analysis-list-state analysis-list-state--error analysis-list-state--inline">
              {cancelError.message}
            </div>
          ) : null}

          <AnalysisList
            cancellingAnalysisIds={cancellingAnalysisIds}
            error={analysisListState.error}
            loading={analysisListState.loading}
            onCancelRow={handleCancelAnalysis}
            onToggleAllSelection={handleToggleAllSelection}
            onToggleRowSelection={handleToggleRowSelection}
            rows={rows}
            selectedAnalysisIds={selectedVisibleAnalysisIds}
          />
        </div>
      </section>

      <CreateAnalysisDialog
        error={createDialogError}
        loading={createAnalysisState.loading}
        onOpenChange={handleCreateDialogOpenChange}
        onSubmit={handleCreateAnalysis}
        open={isCreateDialogOpen}
      />
    </main>
  )
}
