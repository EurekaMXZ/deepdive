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
