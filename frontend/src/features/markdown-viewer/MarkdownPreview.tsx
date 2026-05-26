import { RichMarkdown } from '../markdown-renderer'

type MarkdownPreviewProps = {
  markdown: string
  streaming?: boolean
}

export function MarkdownPreview({ markdown, streaming = false }: MarkdownPreviewProps) {
  return (
    <div className="markdown-preview" aria-live={streaming ? 'polite' : 'off'}>
      <RichMarkdown
        animated={streaming}
        caret={streaming}
        className="markdown-preview__content"
        fallbackClassName="markdown-preview__fallback"
        mode={streaming ? 'streaming' : 'static'}
        value={markdown}
      />
    </div>
  )
}
