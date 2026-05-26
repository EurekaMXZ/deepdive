import type {
  Analysis,
  AnalysisCreated,
  AnalysisListPage,
  AnalysisSuggestion,
  AnalysisSuggestionListPage,
  AnalysisStatus,
} from '../domain/analysis.ts'
import type {
  Permission,
  PermissionListPage,
  Role,
  RoleListPage,
  TokenPair,
  User,
  UserListPage,
  UserRoles,
} from '../domain/auth.ts'
import type {
  DocumentArtifact,
  DocumentArtifactWithContent,
  DocumentListPage,
  DocumentRevision,
  DocumentRevisionListPage,
  DocumentTreeNode,
  DocumentTreePage,
} from '../domain/documents.ts'

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

export type BackendAnalysisSuggestion = {
  repository_label: string
  repository_url: string
  latest_analysis_id: string
  latest_status: AnalysisStatus
  latest_requested_ref: string
  latest_resolved_commit_sha: string | null
  analysis_count: number
  completed_analysis_count: number
  last_analyzed_at: string
}

export type BackendAnalysisSuggestionListPage = {
  items: BackendAnalysisSuggestion[]
}

export type BackendErrorResponse = {
  error?: {
    code?: string
    message?: string
    request_id?: string
    retryable?: boolean
  }
}

export type BackendPermission = {
  id: string
  name: string
  description: string
}

export type BackendRole = {
  id: string
  name: string
  description: string
  permissions: BackendPermission[]
}

export type BackendUser = {
  id: string
  tenant_id: string
  email: string
  display_name: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  roles: BackendRole[]
  permissions: string[]
}

export type BackendTokenPair = {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export type BackendUserListPage = {
  items: BackendUser[]
}

export type BackendRoleListPage = {
  items: BackendRole[]
}

export type BackendPermissionListPage = {
  items: BackendPermission[]
}

export type BackendUserRoles = {
  roles: BackendRole[]
}

export type BackendDocument = {
  document_id: string
  analysis_id: string
  agent_id: string
  title: string
  kind: string
  status: string
  version: number
  content_ref: string
  content_hash: string
  size_bytes: number
}

export type BackendDocumentWithContent = BackendDocument & {
  content: string
}

export type BackendDocumentRevision = {
  revision_id: string
  document_id: string
  version: number
  tool_call_id: string
  operation: string
  content_ref: string
  content_hash: string
  size_bytes: number
  created_at: string
}

export type BackendDocumentListPage = {
  items: BackendDocument[]
}

export type BackendDocumentTreeNode = {
  node_id: string
  node_type: string
  document_id: string | null
  title: string
  slug: string
  path: string
  focus_area: string | null
  sort_order: number
  status: string | null
  version: number | null
  section_count: number
  children: BackendDocumentTreeNode[]
}

export type BackendDocumentTreePage = {
  items: BackendDocumentTreeNode[]
}

export type BackendDocumentRevisionListPage = {
  items: BackendDocumentRevision[]
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

export function fromBackendAnalysisSuggestion(
  value: BackendAnalysisSuggestion,
): AnalysisSuggestion {
  return {
    analysisId: value.latest_analysis_id,
    agentId: '',
    snapshotId: null,
    status: value.latest_status,
    repositoryLabel: value.repository_label,
    repositoryUrl: value.repository_url,
    requestedRef: value.latest_requested_ref,
    resolvedCommitSha: value.latest_resolved_commit_sha,
    updatedAt: value.last_analyzed_at,
  }
}

export function fromBackendAnalysisSuggestionListPage(
  value: BackendAnalysisSuggestionListPage,
): AnalysisSuggestionListPage {
  return {
    items: value.items.map(fromBackendAnalysisSuggestion),
  }
}

export function fromBackendPermission(value: BackendPermission): Permission {
  return {
    id: value.id,
    name: value.name,
    description: value.description,
  }
}

export function fromBackendRole(value: BackendRole): Role {
  return {
    id: value.id,
    name: value.name,
    description: value.description,
    permissions: value.permissions.map(fromBackendPermission),
  }
}

export function fromBackendUser(value: BackendUser): User {
  return {
    id: value.id,
    tenantId: value.tenant_id,
    email: value.email,
    displayName: value.display_name,
    isActive: value.is_active,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
    roles: value.roles.map(fromBackendRole),
    permissions: value.permissions,
  }
}

export function fromBackendTokenPair(value: BackendTokenPair): TokenPair {
  return {
    accessToken: value.access_token,
    refreshToken: value.refresh_token,
    tokenType: value.token_type,
    expiresIn: value.expires_in,
  }
}

export function fromBackendUserListPage(value: BackendUserListPage): UserListPage {
  return {
    items: value.items.map(fromBackendUser),
  }
}

export function fromBackendRoleListPage(value: BackendRoleListPage): RoleListPage {
  return {
    items: value.items.map(fromBackendRole),
  }
}

export function fromBackendPermissionListPage(
  value: BackendPermissionListPage,
): PermissionListPage {
  return {
    items: value.items.map(fromBackendPermission),
  }
}

export function fromBackendUserRoles(value: BackendUserRoles): UserRoles {
  return {
    roles: value.roles.map(fromBackendRole),
  }
}

export function fromBackendDocument(value: BackendDocument): DocumentArtifact {
  return {
    documentId: value.document_id,
    analysisId: value.analysis_id,
    agentId: value.agent_id,
    title: value.title,
    kind: value.kind,
    status: value.status,
    version: value.version,
    contentRef: value.content_ref,
    contentHash: value.content_hash,
    sizeBytes: value.size_bytes,
  }
}

export function fromBackendDocumentWithContent(
  value: BackendDocumentWithContent,
): DocumentArtifactWithContent {
  return {
    ...fromBackendDocument(value),
    content: value.content,
  }
}

export function fromBackendDocumentListPage(
  value: BackendDocumentListPage,
): DocumentListPage {
  return {
    items: value.items.map(fromBackendDocument),
  }
}

export function fromBackendDocumentTreeNode(value: BackendDocumentTreeNode): DocumentTreeNode {
  return {
    nodeId: value.node_id,
    nodeType: value.node_type,
    documentId: value.document_id,
    title: value.title,
    slug: value.slug,
    path: value.path,
    focusArea: value.focus_area,
    sortOrder: value.sort_order,
    status: value.status,
    version: value.version,
    sectionCount: value.section_count,
    children: value.children.map(fromBackendDocumentTreeNode),
  }
}

export function fromBackendDocumentTreePage(value: BackendDocumentTreePage): DocumentTreePage {
  return {
    items: value.items.map(fromBackendDocumentTreeNode),
  }
}

export function fromBackendDocumentRevision(
  value: BackendDocumentRevision,
): DocumentRevision {
  return {
    revisionId: value.revision_id,
    documentId: value.document_id,
    version: value.version,
    toolCallId: value.tool_call_id,
    operation: value.operation,
    contentRef: value.content_ref,
    contentHash: value.content_hash,
    sizeBytes: value.size_bytes,
    createdAt: value.created_at,
  }
}

export function fromBackendDocumentRevisionListPage(
  value: BackendDocumentRevisionListPage,
): DocumentRevisionListPage {
  return {
    items: value.items.map(fromBackendDocumentRevision),
  }
}
