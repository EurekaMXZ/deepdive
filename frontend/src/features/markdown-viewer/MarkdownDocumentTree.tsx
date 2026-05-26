import { ChevronRight, FileText, Folder } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { MarkdownDocumentTreeNode } from '../../domain/markdown.ts'

type MarkdownDocumentTreeProps = {
  nodes: MarkdownDocumentTreeNode[]
  onSelect: (documentId: string) => void
}

export function MarkdownDocumentTree({ nodes, onSelect }: MarkdownDocumentTreeProps) {
  const defaultExpandedNodeIds = useMemo(() => collectExpandedNodeIds(nodes), [nodes])
  const [expandedNodeIds, setExpandedNodeIds] =
    useState<ReadonlySet<string>>(defaultExpandedNodeIds)
  const [collapsedNodeIds, setCollapsedNodeIds] = useState<ReadonlySet<string>>(() => new Set())
  const visibleExpandedNodeIds = useMemo(() => {
    const nodeIds = new Set(expandedNodeIds)
    for (const nodeId of defaultExpandedNodeIds) {
      if (!collapsedNodeIds.has(nodeId)) {
        nodeIds.add(nodeId)
      }
    }
    return nodeIds
  }, [collapsedNodeIds, defaultExpandedNodeIds, expandedNodeIds])

  function toggleNodeExpanded(nodeId: string) {
    if (visibleExpandedNodeIds.has(nodeId)) {
      setExpandedNodeIds((currentNodeIds) => {
        const nextNodeIds = new Set(currentNodeIds)
        nextNodeIds.delete(nodeId)
        return nextNodeIds
      })
      setCollapsedNodeIds((currentNodeIds) => new Set(currentNodeIds).add(nodeId))
      return
    }

    setExpandedNodeIds((currentNodeIds) => {
      const nextNodeIds = new Set(currentNodeIds)
      nextNodeIds.add(nodeId)
      return nextNodeIds
    })
    setCollapsedNodeIds((currentNodeIds) => {
      const nextNodeIds = new Set(currentNodeIds)
      nextNodeIds.delete(nodeId)
      return nextNodeIds
    })
  }

  return (
    <nav className="markdown-document-tree" aria-label="Markdown documents">
      {nodes.map((node) => (
        <MarkdownDocumentTreeItem
          key={node.id}
          expandedNodeIds={visibleExpandedNodeIds}
          node={node}
          onSelect={onSelect}
          onToggleNode={toggleNodeExpanded}
        />
      ))}
    </nav>
  )
}

type MarkdownDocumentTreeItemProps = {
  expandedNodeIds: ReadonlySet<string>
  node: MarkdownDocumentTreeNode
  onSelect: (documentId: string) => void
  onToggleNode: (nodeId: string) => void
}

function MarkdownDocumentTreeItem({
  expandedNodeIds,
  node,
  onSelect,
  onToggleNode,
}: MarkdownDocumentTreeItemProps) {
  const hasChildren = node.children.length > 0
  const selectable = node.selectable !== false
  const expanded = hasChildren && expandedNodeIds.has(node.id)
  const Icon = selectable ? FileText : Folder

  return (
    <div className="markdown-document-tree__item">
      <button
        aria-current={node.active ? 'page' : undefined}
        className="markdown-document-tree__button"
        onClick={() => {
          if (hasChildren) {
            onToggleNode(node.id)
            return
          }

          if (!selectable) {
            return
          }

          onSelect(node.documentId ?? node.id)
        }}
        style={{ paddingLeft: `${10 + node.depth * 14}px` }}
        type="button"
      >
        {hasChildren ? (
          <ChevronRight
            className="markdown-document-tree__chevron"
            data-expanded={expanded}
            size={14}
            aria-hidden="true"
          />
        ) : (
          <span className="markdown-document-tree__spacer" />
        )}
        <Icon size={15} aria-hidden="true" />
        <span>{node.title}</span>
        {node.streaming ? <span className="markdown-document-tree__stream-dot" /> : null}
      </button>
      {expanded ? (
        <nav className="markdown-document-tree" aria-label={`${node.title} children`}>
          {node.children.map((child) => (
            <MarkdownDocumentTreeItem
              key={child.id}
              expandedNodeIds={expandedNodeIds}
              node={child}
              onSelect={onSelect}
              onToggleNode={onToggleNode}
            />
          ))}
        </nav>
      ) : null}
    </div>
  )
}

function collectExpandedNodeIds(nodes: readonly MarkdownDocumentTreeNode[]): ReadonlySet<string> {
  const nodeIds = new Set<string>()
  for (const node of nodes) {
    if (node.expanded) {
      nodeIds.add(node.id)
    }
    for (const childNodeId of collectExpandedNodeIds(node.children)) {
      nodeIds.add(childNodeId)
    }
  }
  return nodeIds
}
