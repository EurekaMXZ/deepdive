import type { MarkdownHeading } from '../../domain/markdown.ts'

type MarkdownOutlineProps = {
  headings: MarkdownHeading[]
  onNavigate?: (headingId: string) => void
}

export function MarkdownOutline({ headings, onNavigate }: MarkdownOutlineProps) {
  return (
    <nav className="markdown-outline" aria-label="Markdown sections">
      {headings.length > 0 ? (
        headings.map((heading) => (
          <a
            className="markdown-outline__item"
            data-depth={heading.depth}
            href={`#${heading.id}`}
            key={heading.id}
            onClick={(event) => {
              event.preventDefault()
              onNavigate?.(heading.id)
            }}
          >
            {heading.title}
          </a>
        ))
      ) : (
        <span className="markdown-outline__empty">无章节</span>
      )}
    </nav>
  )
}
