import { RichMarkdown } from '../markdown-renderer'

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
    <RichMarkdown
      animated={animated}
      caret={streaming}
      className={className}
      fallbackClassName={fallbackClassName}
      mode={streaming ? 'streaming' : 'static'}
      value={value}
    />
  )
}
