import { code } from '@streamdown/code'
import { cjk } from '@streamdown/cjk'
import { math } from '@streamdown/math'
import { mermaid } from '@streamdown/mermaid'
import { lazy, Suspense } from 'react'
import 'katex/dist/katex.min.css'
import 'streamdown/styles.css'

const Streamdown = lazy(() => import('streamdown').then((module) => ({ default: module.Streamdown })))

export type RichMarkdownMode = 'static' | 'streaming'

export type RichMarkdownProps = {
  animated?: boolean
  ariaLive?: 'off' | 'polite'
  caret?: boolean
  className: string
  fallbackClassName: string
  mode?: RichMarkdownMode
  value: string
}

export function RichMarkdown({
  animated = false,
  ariaLive,
  caret = false,
  className,
  fallbackClassName,
  mode = 'static',
  value,
}: RichMarkdownProps) {
  const streaming = mode === 'streaming'

  return (
    <Suspense fallback={<pre className={fallbackClassName}>{value}</pre>}>
      <Streamdown
        animated={animated && streaming ? { animation: 'fadeIn', duration: 120, stagger: 12 } : false}
        aria-live={ariaLive}
        caret={caret && streaming ? 'block' : undefined}
        className={`rich-markdown ${className}`}
        controls={{
          code: { copy: true, download: true },
          mermaid: { fullscreen: true, download: true, copy: true, panZoom: true },
          table: { copy: true, download: true, fullscreen: true },
        }}
        isAnimating={streaming}
        lineNumbers={true}
        mermaid={{
          config: {
            fontFamily: 'ui-monospace, SFMono-Regular, Consolas, Liberation Mono, monospace',
            theme: 'dark',
          },
        }}
        mode={mode}
        parseIncompleteMarkdown={streaming}
        plugins={{ code, mermaid, math, cjk }}
        shikiTheme={['github-dark', 'github-dark']}
        skipHtml
      >
        {value}
      </Streamdown>
    </Suspense>
  )
}
