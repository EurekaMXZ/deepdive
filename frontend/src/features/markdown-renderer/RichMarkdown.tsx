import { createCodePlugin } from '@streamdown/code'
import { cjk } from '@streamdown/cjk'
import { math } from '@streamdown/math'
import { mermaid } from '@streamdown/mermaid'
import { lazy, Suspense } from 'react'
import type { ComponentPropsWithoutRef, ComponentType } from 'react'
import type { CustomRendererProps } from 'streamdown'
import type { Components, ExtraProps } from 'streamdown'
import 'katex/dist/katex.min.css'
import 'streamdown/styles.css'

import type { MarkdownHeading } from '../../domain/markdown.ts'

const Streamdown = lazy(() => import('streamdown').then((module) => ({ default: module.Streamdown })))
const StreamdownCodeBlock = lazy(() => import('streamdown').then((module) => ({ default: module.CodeBlock })))
const markdownCode = createCodePlugin({
  themes: ['github-dark', 'github-dark'],
})

type CodeFenceMetadata = {
  disableLineNumbers: boolean
  reference?: string
  source?: string
  startLine?: number
}

const CODE_RENDERER_LANGUAGES = [
  'bash',
  'bat',
  'c',
  'cmd',
  'cpp',
  'csharp',
  'css',
  'diff',
  'dockerfile',
  'go',
  'graphql',
  'html',
  'ini',
  'java',
  'javascript',
  'js',
  'json',
  'jsonc',
  'jsx',
  'kotlin',
  'lua',
  'makefile',
  'markdown',
  'md',
  'nginx',
  'php',
  'plaintext',
  'powershell',
  'prisma',
  'properties',
  'python',
  'rb',
  'rs',
  'ruby',
  'rust',
  'sh',
  'shell',
  'sql',
  'swift',
  'text',
  'toml',
  'ts',
  'tsx',
  'typescript',
  'vue',
  'xml',
  'yaml',
  'yml',
  'zsh',
]

const SOURCE_META_KEYS = new Set(['file', 'filename', 'location', 'path', 'source', 'src'])
const REFERENCE_META_KEYS = new Set(['cite', 'citation', 'evidence', 'ref', 'reference'])
const META_TOKEN_PATTERN = /(?:[^\s"']+|"[^"]*"|'[^']*')+/g

export type RichMarkdownMode = 'static' | 'streaming'

export type MarkdownHeadingId = MarkdownHeading

export type RichMarkdownProps = {
  animated?: boolean
  ariaLive?: 'off' | 'polite'
  caret?: boolean
  className: string
  fallbackClassName: string
  headingIds?: MarkdownHeadingId[]
  mode?: RichMarkdownMode
  value: string
}

type HeadingComponentProps = ComponentPropsWithoutRef<'h1'> & ExtraProps
type LinkComponentProps = ComponentPropsWithoutRef<'a'> & ExtraProps
type BlockquoteComponentProps = ComponentPropsWithoutRef<'blockquote'> & ExtraProps
type InlineCodeComponentProps = ComponentPropsWithoutRef<'code'> & ExtraProps

type PositionedNode = {
  position?: {
    start?: {
      line?: number
    }
  }
}

function sourceLineFromHeadingNode(node: HeadingComponentProps['node']): number | undefined {
  // Streamdown exposes node.position.start.line for source-line anchoring.
  const line = (node as PositionedNode | undefined)?.position?.start?.line
  return typeof line === 'number' ? line : undefined
}

function stripMetaQuotes(value: string) {
  const trimmed = value.trim()

  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1)
  }

  return trimmed
}

function looksLikeSourceLocation(token: string) {
  return (
    /[\\/]/.test(token) ||
    /^[\w.-]+\.[\w-]+(?::\d+(?:-\d+)?)?(?:#L\d+(?:-L?\d+)?)?$/.test(token)
  )
}

function parseCodeFenceMetadata(meta: string | undefined): CodeFenceMetadata {
  const metadata: CodeFenceMetadata = {
    disableLineNumbers: false,
  }

  for (const token of meta?.match(META_TOKEN_PATTERN) ?? []) {
    const separatorIndex = token.indexOf('=')
    const key = separatorIndex > 0 ? token.slice(0, separatorIndex).trim().toLowerCase() : ''
    const value = separatorIndex > 0 ? stripMetaQuotes(token.slice(separatorIndex + 1)) : stripMetaQuotes(token)

    if (!value || /^\{.*\}$/.test(value)) {
      continue
    }

    if (token === 'noLineNumbers') {
      metadata.disableLineNumbers = true
      continue
    }

    if (key === 'startline') {
      const startLine = Number.parseInt(value, 10)
      if (Number.isInteger(startLine) && startLine >= 1) {
        metadata.startLine = startLine
      }
      continue
    }

    if (SOURCE_META_KEYS.has(key)) {
      metadata.source = value
      continue
    }

    if (REFERENCE_META_KEYS.has(key)) {
      metadata.reference = value
      continue
    }

    if (!key && !metadata.source && looksLikeSourceLocation(value)) {
      metadata.source = value
    }
  }

  return metadata
}

function RichCodeBlock({ code, language, meta, isIncomplete }: CustomRendererProps) {
  const metadata = parseCodeFenceMetadata(meta)
  const languageLabel = language || 'text'

  return (
    <div data-rich-code-frame>
      <div data-rich-code-header>
        <span data-rich-code-language>{languageLabel}</span>
        {metadata.source ? (
          <span data-rich-code-source title={metadata.source}>
            {metadata.source}
          </span>
        ) : null}
        {metadata.reference ? (
          <span data-rich-code-reference title={`引用参考: ${metadata.reference}`}>
            引用 {metadata.reference}
          </span>
        ) : null}
      </div>
      <Suspense fallback={<pre data-rich-code-fallback>{code}</pre>}>
        <StreamdownCodeBlock
          code={code}
          isIncomplete={isIncomplete}
          language={languageLabel}
          lineNumbers={!metadata.disableLineNumbers}
          startLine={metadata.startLine}
        />
      </Suspense>
    </div>
  )
}

const codeRenderers = [{ language: CODE_RENDERER_LANGUAGES, component: RichCodeBlock }]

function RichMarkdownLink({ children, href, ...props }: LinkComponentProps) {
  return (
    <a
      {...props}
      data-rich-link
      href={href}
      rel={isExternalHref(href) ? 'noreferrer' : props.rel}
      target={isExternalHref(href) ? '_blank' : undefined}
    >
      {children}
    </a>
  )
}

function RichMarkdownBlockquote({ children, ...props }: BlockquoteComponentProps) {
  return (
    <blockquote {...props} data-rich-blockquote>
      {children}
    </blockquote>
  )
}

function RichMarkdownInlineCode({ children, ...props }: InlineCodeComponentProps) {
  return (
    <code {...props} data-rich-inline-code>
      {children}
    </code>
  )
}

function isExternalHref(href: string | undefined): boolean {
  return href !== undefined && /^https?:\/\//i.test(href)
}

function createHeadingComponent(
  tagName: 'h1' | 'h2' | 'h3',
  headingIdByLine: ReadonlyMap<number, string>,
): ComponentType<HeadingComponentProps> {
  const Tag = tagName
  const depth = Number.parseInt(tagName.slice(1), 10)

  return function MarkdownHeadingComponent({ children, node, ...props }: HeadingComponentProps) {
    const headingLine = sourceLineFromHeadingNode(node)
    const headingId = typeof headingLine === 'number' ? headingIdByLine.get(headingLine) : undefined

    return (
      <Tag {...props} id={headingId ?? props.id} data-streamdown={`heading-${depth}`}>
        {children}
      </Tag>
    )
  }
}

function createMarkdownComponents(headingIds: MarkdownHeadingId[] | undefined): Components {
  const components: Components = {
    a: RichMarkdownLink,
    blockquote: RichMarkdownBlockquote,
    inlineCode: RichMarkdownInlineCode,
  }

  if (!headingIds || headingIds.length === 0) {
    return components
  }

  const headingIdByLine = new Map(headingIds.map((heading) => [heading.line, heading.id]))

  return {
    ...components,
    h1: createHeadingComponent('h1', headingIdByLine),
    h2: createHeadingComponent('h2', headingIdByLine),
    h3: createHeadingComponent('h3', headingIdByLine),
  }
}

export function RichMarkdown({
  animated = false,
  ariaLive,
  caret = false,
  className,
  fallbackClassName,
  headingIds,
  mode = 'static',
  value,
}: RichMarkdownProps) {
  const streaming = mode === 'streaming'
  const headingComponents = createMarkdownComponents(headingIds)

  return (
    <Suspense fallback={<pre className={fallbackClassName}>{value}</pre>}>
      <Streamdown
        animated={animated && streaming ? { animation: 'fadeIn', duration: 120, stagger: 12 } : false}
        aria-live={ariaLive}
        caret={caret && streaming ? 'block' : undefined}
        className={`rich-markdown ${className}`}
        components={headingComponents}
        controls={false}
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
        plugins={{ code: markdownCode, mermaid, math, cjk, renderers: codeRenderers }}
        skipHtml
      >
        {value}
      </Streamdown>
    </Suspense>
  )
}
