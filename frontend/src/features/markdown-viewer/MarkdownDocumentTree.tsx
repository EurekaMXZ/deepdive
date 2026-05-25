import { ChevronRight, FileText, Folder } from 'lucide-react'

import type { MarkdownDocumentTreeNode } from '../../domain/markdown.ts'

type MarkdownDocumentTreeProps = {
  nodes: MarkdownDocumentTreeNode[]
  onSelect: (documentId: string) => void
}

export function MarkdownDocumentTree({ nodes, onSelect }: MarkdownDocumentTreeProps) {
  return (
    <nav className="markdown-document-tree" aria-label="Markdown documents">
      {nodes.map((node) => (
        <MarkdownDocumentTreeItem key={node.id} node={node} onSelect={onSelect} />
      ))}
    </nav>
  )
}

type MarkdownDocumentTreeItemProps = {
  node: MarkdownDocumentTreeNode
  onSelect: (documentId: string) => void
}

function MarkdownDocumentTreeItem({ node, onSelect }: MarkdownDocumentTreeItemProps) {
  const hasChildren = node.children.length > 0
  const Icon = hasChildren ? Folder : FileText

  return (
    <div className="markdown-document-tree__item">
      <button
        aria-current={node.active ? 'page' : undefined}
        className="markdown-document-tree__button"
        onClick={() => onSelect(node.id)}
        style={{ paddingLeft: `${10 + node.depth * 14}px` }}
        type="button"
      >
        {hasChildren ? (
          <ChevronRight
            className="markdown-document-tree__chevron"
            data-expanded={node.expanded}
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
      {node.expanded ? <MarkdownDocumentTree nodes={node.children} onSelect={onSelect} /> : null}
    </div>
  )
}
