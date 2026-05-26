import { RichMarkdown } from '../markdown-renderer'
import type { MarkdownHeading } from '../../domain/markdown.ts'

type MarkdownPreviewProps = {
  headings?: MarkdownHeading[]
  markdown: string
  streaming?: boolean
}

export function MarkdownPreview({ headings, markdown, streaming = false }: MarkdownPreviewProps) {
  return (
    <div className="markdown-preview" aria-live={streaming ? 'polite' : 'off'}>
      <RichMarkdown
        animated={streaming}
        caret={streaming}
        className="markdown-preview__content"
        fallbackClassName="markdown-preview__fallback"
        headingIds={headings}
        mode={streaming ? 'streaming' : 'static'}
        value={markdown}
      />
    </div>
  )
}
