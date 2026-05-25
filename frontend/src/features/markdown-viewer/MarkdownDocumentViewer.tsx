import { useMemo } from 'react'

import {
  buildMarkdownDocumentTree,
  extractMarkdownHeadings,
  findMarkdownDocument,
  flattenMarkdownDocuments,
  type MarkdownDocumentNode,
} from '../../domain/markdown.ts'
import { MarkdownDocumentTree } from './MarkdownDocumentTree.tsx'
import { MarkdownOutline } from './MarkdownOutline.tsx'
import { MarkdownPreview } from './MarkdownPreview.tsx'

export type MarkdownDocumentViewerProps = {
  activeDocumentId: string | null
  documents: MarkdownDocumentNode[]
  onDocumentSelect?: (documentId: string) => void
}

export function MarkdownDocumentViewer({
  activeDocumentId,
  documents,
  onDocumentSelect,
}: MarkdownDocumentViewerProps) {
  const flattenedDocuments = useMemo(() => flattenMarkdownDocuments(documents), [documents])
  const fallbackDocument = flattenedDocuments.find((document) => document.markdown !== undefined) ?? null
  const activeDocument =
    findMarkdownDocument(documents, activeDocumentId) ??
    findMarkdownDocument(documents, fallbackDocument?.id ?? null)
  const activeMarkdown = activeDocument?.markdown ?? ''
  const tree = useMemo(
    () => buildMarkdownDocumentTree(documents, activeDocument?.id ?? null),
    [activeDocument?.id, documents],
  )
  const headings = useMemo(() => extractMarkdownHeadings(activeMarkdown), [activeMarkdown])

  return (
    <section className="markdown-viewer" aria-label="Markdown document viewer">
      <aside className="markdown-viewer__sidebar">
        <div className="markdown-viewer__panel-label">文档</div>
        <MarkdownDocumentTree
          nodes={tree}
          onSelect={(documentId) => {
            onDocumentSelect?.(documentId)
          }}
        />
      </aside>

      <main className="markdown-viewer__main" aria-label={activeDocument?.title ?? 'Markdown preview'}>
        <div className="markdown-viewer__titlebar">
          <span>{activeDocument?.title ?? '未选择文档'}</span>
          {activeDocument?.streaming ? <span className="markdown-viewer__streaming">生成中</span> : null}
        </div>
        <MarkdownPreview markdown={activeMarkdown} streaming={activeDocument?.streaming} />
      </main>

      <aside className="markdown-viewer__outline">
        <div className="markdown-viewer__panel-label">章节</div>
        <MarkdownOutline headings={headings} />
      </aside>
    </section>
  )
}
