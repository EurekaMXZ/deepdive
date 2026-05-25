import { useEffect, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router'

import { WorkspaceTopbar } from '../../components/WorkspaceTopbar'
import { canCancelAnalysisStatus } from '../../domain'
import { useAnalysisDetail, useAnalysisEvents } from '../../hooks'
import { AnalysisPreview } from './AnalysisPreview'

type AnalysisDetailPageProps = {
  accessToken?: string | (() => string | null | undefined)
  apiBaseUrl?: string
}

export function AnalysisDetailPage({
  accessToken,
  apiBaseUrl,
}: AnalysisDetailPageProps) {
  const navigate = useNavigate()
  const { analysisId } = useParams<{ analysisId: string }>()
  const [isCancelling, setIsCancelling] = useState(false)
  const analysisState = useAnalysisDetail({ accessToken, baseUrl: apiBaseUrl })
  const stream = useAnalysisEvents({
    accessToken,
    analysisId: analysisId ?? null,
    baseUrl: apiBaseUrl,
    enabled: Boolean(analysisId),
  })
  const { loadAnalysis } = analysisState
  const cancelSourceStatuses = [stream.status, analysisState.data?.status].filter(
    (status) => status !== null && status !== undefined,
  )
  const canCancel =
    Boolean(analysisId) &&
    cancelSourceStatuses.length > 0 &&
    cancelSourceStatuses.every(canCancelAnalysisStatus)

  useEffect(() => {
    if (!analysisId) {
      return
    }

    void loadAnalysis(analysisId).catch(() => undefined)
  }, [analysisId, loadAnalysis])

  async function handleCancelAnalysis() {
    if (!analysisId || isCancelling || !canCancel) {
      return
    }

    setIsCancelling(true)
    try {
      await analysisState.cancelAnalysis(analysisId)
    } finally {
      setIsCancelling(false)
    }
  }

  if (!analysisId) {
    return <Navigate to="/analysis" replace />
  }

  return (
    <main className="workspace workspace--analysis-detail" aria-label="分析对话">
      <WorkspaceTopbar title="分析对话" />
      <section className="workspace-body workspace-body--full">
        <AnalysisPreview
          analysisId={analysisId}
          createError={analysisState.error}
          canCancel={canCancel}
          isCancelling={isCancelling}
          isCreating={analysisState.loading && analysisState.data === null}
          onBack={() => navigate('/analysis')}
          onCancel={handleCancelAnalysis}
          repositoryUrl={analysisState.data?.repositoryUrl ?? analysisId}
          stream={stream}
        />
      </section>
    </main>
  )
}
