import { useEffect, useMemo } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router'

import { WorkspaceTopbar } from '../../components/WorkspaceTopbar'
import { markdownNodesFromDocumentList, type DocumentArtifact } from '../../domain'
import { MarkdownDocumentViewer } from '../markdown-viewer'
import { useAnalysisDocumentsApi } from '../../hooks'

type AnalysisDocumentsPageProps = {
  accessToken?: string | (() => string | null | undefined)
  apiBaseUrl?: string
}

const EMPTY_DOCUMENTS: DocumentArtifact[] = []

export function AnalysisDocumentsPage({
  accessToken,
  apiBaseUrl,
}: AnalysisDocumentsPageProps) {
  const navigate = useNavigate()
  const { analysisId, documentId } = useParams<{
    analysisId: string
    documentId?: string
  }>()
  const documentsApi = useAnalysisDocumentsApi({ accessToken, baseUrl: apiBaseUrl })
  const documents = documentsApi.documents.data?.items ?? EMPTY_DOCUMENTS
  const activeDocumentId = documentId ?? documents[0]?.documentId ?? null
  const content = documentsApi.content.data
  const loadDocuments = documentsApi.loadDocuments
  const loadDocumentContent = documentsApi.loadDocumentContent

  useEffect(() => {
    if (!analysisId) {
      return
    }

    void loadDocuments(analysisId).catch(() => undefined)
  }, [analysisId, loadDocuments])

  useEffect(() => {
    if (!analysisId || !activeDocumentId) {
      return
    }

    void loadDocumentContent(analysisId, activeDocumentId).catch(() => undefined)
  }, [analysisId, activeDocumentId, loadDocumentContent])

  useEffect(() => {
    if (!analysisId || documentId || documents.length === 0) {
      return
    }

    navigate(documentRoute(analysisId, documents[0].documentId), { replace: true })
  }, [analysisId, documentId, documents, navigate])

  const viewerDocuments = useMemo(
    () => markdownNodesFromDocumentList(documents, content),
    [content, documents],
  )

  if (!analysisId) {
    return <Navigate to="/analysis" replace />
  }

  if (documentsApi.documents.loading && documents.length === 0) {
    return (
      <main className="workspace workspace--documents" aria-label="文档预览">
        <WorkspaceTopbar title="文档预览" />
        <section className="workspace-body workspace-body--full">
          <div className="document-preview-state">加载文档</div>
        </section>
      </main>
    )
  }

  const error = documentsApi.documents.error ?? documentsApi.content.error
  if (error) {
    return (
      <main className="workspace workspace--documents" aria-label="文档预览">
        <WorkspaceTopbar title="文档预览" />
        <section className="workspace-body workspace-body--full">
          <div className="document-preview-state document-preview-state--error">
            {error.message}
          </div>
        </section>
      </main>
    )
  }

  if (documents.length === 0) {
    return (
      <main className="workspace workspace--documents" aria-label="文档预览">
        <WorkspaceTopbar title="文档预览" />
        <section className="workspace-body workspace-body--full">
          <div className="document-preview-state">暂无文档</div>
        </section>
      </main>
    )
  }

  return (
    <main className="workspace workspace--documents" aria-label="文档预览">
      <WorkspaceTopbar title="文档预览" />
      <section className="workspace-body workspace-body--full">
        <MarkdownDocumentViewer
          activeDocumentId={activeDocumentId}
          documents={viewerDocuments}
          onDocumentSelect={(nextDocumentId) => {
            navigate(documentRoute(analysisId, nextDocumentId))
          }}
        />
      </section>
    </main>
  )
}

function documentRoute(analysisId: string, documentId: string): string {
  return `/analysis/${encodeURIComponent(analysisId)}/documents/${encodeURIComponent(documentId)}`
}
