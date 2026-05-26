import type { AgentId, AnalysisId } from './analysis.ts'

export type DocumentArtifact = {
  documentId: string
  analysisId: AnalysisId
  agentId: AgentId
  title: string
  kind: string
  status: string
  version: number
  contentRef: string
  contentHash: string
  sizeBytes: number
}

export type DocumentArtifactWithContent = DocumentArtifact & {
  content: string
}

export type DocumentTreeNode = {
  nodeId: string
  nodeType: string
  documentId: string | null
  title: string
  slug: string
  path: string
  focusArea: string | null
  sortOrder: number
  status: string | null
  version: number | null
  sectionCount: number
  children: DocumentTreeNode[]
}

export type DocumentTreePage = {
  items: DocumentTreeNode[]
}

export type DocumentRevision = {
  revisionId: string
  documentId: string
  version: number
  toolCallId: string
  operation: string
  contentRef: string
  contentHash: string
  sizeBytes: number
  createdAt: string
}

export type DocumentListPage = {
  items: DocumentArtifact[]
}

export type DocumentRevisionListPage = {
  items: DocumentRevision[]
}
