import { FileText, ListTree } from 'lucide-react'
import { useMemo, useState } from 'react'

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
  const [mobilePanel, setMobilePanel] = useState<'documents' | 'outline' | null>(null)
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

  function handleOutlineNavigate(headingId: string) {
    const heading = document.getElementById(headingId)
    heading?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    window.history.replaceState(null, '', `#${headingId}`)
    setMobilePanel(null)
  }

  return (
    <section className="markdown-viewer" aria-label="Markdown document viewer">
      <div className="markdown-viewer__mobile-actions" aria-label="移动端文档导航">
        <button
          aria-label="打开文档树"
          className="markdown-viewer__mobile-button"
          onClick={() => setMobilePanel('documents')}
          type="button"
        >
          <FileText size={18} aria-hidden="true" />
        </button>
        <button
          aria-label="打开目录树"
          className="markdown-viewer__mobile-button"
          onClick={() => setMobilePanel('outline')}
          type="button"
        >
          <ListTree size={18} aria-hidden="true" />
        </button>
      </div>

      {mobilePanel ? (
        <button
          aria-label="关闭文档面板"
          className="markdown-viewer__mobile-backdrop"
          onClick={() => setMobilePanel(null)}
          type="button"
        />
      ) : null}

      <aside
        className="markdown-viewer__sidebar"
        data-mobile-panel={mobilePanel === 'documents' ? 'open' : 'closed'}
      >
        <div className="markdown-viewer__panel-label">文档</div>
        <MarkdownDocumentTree
          nodes={tree}
          onSelect={(documentId) => {
            onDocumentSelect?.(documentId)
            setMobilePanel(null)
          }}
        />
      </aside>

      <main className="markdown-viewer__main" aria-label={activeDocument?.title ?? 'Markdown preview'}>
        <div className="markdown-viewer__titlebar">
          <span>{activeDocument?.title ?? '未选择文档'}</span>
          {activeDocument?.streaming ? <span className="markdown-viewer__streaming">生成中</span> : null}
        </div>
        <MarkdownPreview headings={headings} markdown={activeMarkdown} streaming={activeDocument?.streaming} />
      </main>

      <aside
        className="markdown-viewer__outline"
        data-mobile-panel={mobilePanel === 'outline' ? 'open' : 'closed'}
      >
        <div className="markdown-viewer__panel-label">章节</div>
        <MarkdownOutline headings={headings} onNavigate={handleOutlineNavigate} />
      </aside>
    </section>
  )
}
