import type { DocumentArtifact, DocumentArtifactWithContent, DocumentTreeNode } from './documents.ts'

export type MarkdownDocumentNode = {
  id: string
  documentId?: string | null
  title: string
  path?: string
  markdown?: string
  selectable?: boolean
  streaming?: boolean
  children?: MarkdownDocumentNode[]
}

export type MarkdownDocumentTreeNode = Omit<MarkdownDocumentNode, 'children'> & {
  active: boolean
  depth: number
  expanded: boolean
  children: MarkdownDocumentTreeNode[]
}

export type MarkdownHeading = {
  id: string
  depth: 1 | 2 | 3
  line: number
  title: string
}

export function flattenMarkdownDocuments(
  documents: readonly MarkdownDocumentNode[],
): MarkdownDocumentNode[] {
  return documents.flatMap((document) => [
    document,
    ...flattenMarkdownDocuments(document.children ?? []),
  ])
}

export function findMarkdownDocument(
  documents: readonly MarkdownDocumentNode[],
  documentId: string | null,
): MarkdownDocumentNode | null {
  if (documentId === null) {
    return null
  }

  return flattenMarkdownDocuments(documents).find((document) => document.id === documentId) ?? null
}

export function findFirstMarkdownDocument(
  documents: readonly MarkdownDocumentNode[],
): MarkdownDocumentNode | null {
  return flattenMarkdownDocuments(documents).find((document) => document.selectable !== false) ?? null
}

export function buildMarkdownDocumentTree(
  documents: readonly MarkdownDocumentNode[],
  activeDocumentId: string | null,
): MarkdownDocumentTreeNode[] {
  return documents.map((document) => buildTreeNode(document, activeDocumentId, 0))
}

export function extractMarkdownHeadings(markdown: string): MarkdownHeading[] {
  const headings: MarkdownHeading[] = []
  const usedSlugs = new Map<string, number>()
  let inFence = false

  for (const [index, line] of markdown.split(/\r?\n/).entries()) {
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence) {
      continue
    }

    const match = /^(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line)
    if (!match) {
      continue
    }

    const title = stripInlineMarkdown(match[2]).trim()
    if (!title) {
      continue
    }

    headings.push({
      id: uniqueSlug(slugify(title), usedSlugs),
      depth: match[1].length as MarkdownHeading['depth'],
      line: index + 1,
      title,
    })
  }

  return headings
}

export function markdownNodesFromDocumentArtifacts(
  documents: DocumentArtifactWithContent[],
): MarkdownDocumentNode[] {
  return sortMarkdownDocuments(documents)
    .map((document) => ({
      id: document.documentId,
      title: document.title,
      path: document.title,
      markdown: document.content,
      streaming: isStreamingDocumentStatus(document.status),
      children: [],
    }))
}

export function markdownNodesFromDocumentList(
  documents: DocumentArtifact[],
  activeDocumentContent: DocumentArtifactWithContent | null,
): MarkdownDocumentNode[] {
  return sortMarkdownDocuments(documents)
    .map((document) => ({
      id: document.documentId,
      title: document.title,
      path: document.title,
      markdown:
        activeDocumentContent?.documentId === document.documentId
          ? activeDocumentContent.content
          : undefined,
      streaming: isStreamingDocumentStatus(document.status),
      children: [],
    }))
}

export function markdownNodesFromDocumentTree(
  nodes: DocumentTreeNode[],
  activeDocumentContent: DocumentArtifactWithContent | null,
): MarkdownDocumentNode[] {
  return nodes
    .map((node) => markdownNodeFromDocumentTreeNode(node, activeDocumentContent))
    .sort(compareMarkdownDocumentNodes)
}

function isStreamingDocumentStatus(status: string): boolean {
  return status === 'generating' || status === 'streaming' || status === 'in_progress' || status === 'updating'
}

function sortMarkdownDocuments<T extends DocumentArtifact>(documents: T[]): T[] {
  return [...documents].sort((left, right) => {
    const statusRank = documentStatusRank(left.status) - documentStatusRank(right.status)
    return statusRank || left.title.localeCompare(right.title)
  })
}

function documentStatusRank(status: string): number {
  if (status === 'finalized') {
    return 0
  }
  if (status === 'draft') {
    return 1
  }
  return 2
}

function markdownNodeFromDocumentTreeNode(
  node: DocumentTreeNode,
  activeDocumentContent: DocumentArtifactWithContent | null,
): MarkdownDocumentNode {
  const documentId = node.documentId
  const selectable = documentId !== null

  const markdownNode: MarkdownDocumentNode = {
    id: documentId ?? node.nodeId,
    documentId,
    title: node.title,
    path: node.path,
    selectable,
    streaming: node.status === null ? false : isStreamingDocumentStatus(node.status),
    children: node.children
      .map((child) => markdownNodeFromDocumentTreeNode(child, activeDocumentContent))
      .sort(compareMarkdownDocumentNodes),
  }

  if (documentId !== null) {
    markdownNode.markdown =
      activeDocumentContent?.documentId === documentId ? activeDocumentContent.content : undefined
  }

  return markdownNode
}

function compareMarkdownDocumentNodes(left: MarkdownDocumentNode, right: MarkdownDocumentNode): number {
  return (left.path ?? left.title).localeCompare(right.path ?? right.title)
}

function buildTreeNode(
  document: MarkdownDocumentNode,
  activeDocumentId: string | null,
  depth: number,
): MarkdownDocumentTreeNode {
  const children = (document.children ?? []).map((child) =>
    buildTreeNode(child, activeDocumentId, depth + 1),
  )
  const active = document.id === activeDocumentId

  return {
    ...document,
    active,
    children,
    depth,
    expanded: children.length > 0 && (active || children.some((child) => child.active || child.expanded)),
  }
}

function stripInlineMarkdown(value: string): string {
  return value
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_~]/g, '')
}

function slugify(value: string): string {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/&/g, ' ')
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, '-')
    .replace(/^-+|-+$/g, '')

  return slug || 'section'
}

function uniqueSlug(value: string, usedSlugs: Map<string, number>): string {
  const nextCount = (usedSlugs.get(value) ?? 0) + 1
  usedSlugs.set(value, nextCount)
  return nextCount === 1 ? value : `${value}-${nextCount}`
}
