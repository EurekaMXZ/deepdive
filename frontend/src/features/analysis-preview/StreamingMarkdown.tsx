import { lazy, Suspense } from 'react'

const Streamdown = lazy(() => import('streamdown').then((module) => ({ default: module.Streamdown })))

type StreamingMarkdownProps = {
  animated?: boolean
  className: string
  fallbackClassName: string
  streaming?: boolean
  value: string
}

export function StreamingMarkdown({
  animated = false,
  className,
  fallbackClassName,
  streaming = false,
  value,
}: StreamingMarkdownProps) {
  return (
    <Suspense fallback={<pre className={fallbackClassName}>{value}</pre>}>
      <Streamdown
        animated={animated && streaming ? { animation: 'fadeIn', duration: 120, stagger: 12 } : false}
        caret={streaming ? 'block' : undefined}
        className={className}
        controls={false}
        isAnimating={streaming}
        lineNumbers={false}
        mode={streaming ? 'streaming' : 'static'}
        parseIncompleteMarkdown={streaming}
        skipHtml
      >
        {value}
      </Streamdown>
    </Suspense>
  )
}
