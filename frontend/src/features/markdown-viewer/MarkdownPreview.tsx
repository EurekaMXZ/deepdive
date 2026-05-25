import { lazy, Suspense } from 'react'

const Streamdown = lazy(() => import('streamdown').then((module) => ({ default: module.Streamdown })))

type MarkdownPreviewProps = {
  markdown: string
  streaming?: boolean
}

export function MarkdownPreview({ markdown, streaming = false }: MarkdownPreviewProps) {
  return (
    <div className="markdown-preview" aria-live={streaming ? 'polite' : 'off'}>
      <Suspense fallback={<pre className="markdown-preview__fallback">{markdown}</pre>}>
        <Streamdown
          animated={streaming ? { animation: 'fadeIn', duration: 120, stagger: 12 } : false}
          caret={streaming ? 'block' : undefined}
          className="markdown-preview__content"
          controls={false}
          isAnimating={streaming}
          lineNumbers={false}
          mode={streaming ? 'streaming' : 'static'}
          parseIncompleteMarkdown={streaming}
          skipHtml
        >
          {markdown}
        </Streamdown>
      </Suspense>
    </div>
  )
}
