import { useEffect, useMemo } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router'

import { WorkspaceTopbar } from '../../components/WorkspaceTopbar'
import {
  findFirstMarkdownDocument,
  markdownNodesFromDocumentTree,
  type DocumentTreeNode,
} from '../../domain'
import { MarkdownDocumentViewer } from '../markdown-viewer'
import { useAnalysisDocumentsApi } from '../../hooks'

type AnalysisDocumentsPageProps = {
  accessToken?: string | (() => string | null | undefined)
  apiBaseUrl?: string
}

const EMPTY_DOCUMENT_TREE: DocumentTreeNode[] = []

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
  const documentTree = documentsApi.documentTree.data?.items ?? EMPTY_DOCUMENT_TREE
  const content = documentsApi.content.data
  const viewerDocuments = useMemo(
    () => markdownNodesFromDocumentTree(documentTree, content),
    [content, documentTree],
  )
  const fallbackDocument = useMemo(() => findFirstMarkdownDocument(viewerDocuments), [viewerDocuments])
  const activeDocumentId = documentId ?? fallbackDocument?.documentId ?? null
  const loadDocumentTree = documentsApi.loadDocumentTree
  const loadDocumentContent = documentsApi.loadDocumentContent

  useEffect(() => {
    if (!analysisId) {
      return
    }

    void loadDocumentTree(analysisId).catch(() => undefined)
  }, [analysisId, loadDocumentTree])

  useEffect(() => {
    if (!analysisId || !activeDocumentId) {
      return
    }

    void loadDocumentContent(analysisId, activeDocumentId).catch(() => undefined)
  }, [analysisId, activeDocumentId, loadDocumentContent])

  useEffect(() => {
    if (!analysisId || documentId || !fallbackDocument?.documentId) {
      return
    }

    navigate(documentRoute(analysisId, fallbackDocument.documentId), { replace: true })
  }, [analysisId, documentId, fallbackDocument, navigate])

  if (!analysisId) {
    return <Navigate to="/analysis" replace />
  }

  if (documentsApi.documentTree.loading && documentTree.length === 0) {
    return (
      <main className="workspace workspace--documents" aria-label="文档预览">
        <WorkspaceTopbar title="文档预览" />
        <section className="workspace-body workspace-body--full">
          <div className="document-preview-state">加载文档</div>
        </section>
      </main>
    )
  }

  const error = documentsApi.documentTree.error ?? documentsApi.content.error
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

  if (documentTree.length === 0) {
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
