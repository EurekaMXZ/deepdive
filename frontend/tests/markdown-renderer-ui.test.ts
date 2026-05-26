import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const richMarkdown = readFileSync(resolve('src/features/markdown-renderer/RichMarkdown.tsx'), 'utf8')
const appCss = readFileSync(resolve('src/App.css'), 'utf8').replace(/\r\n/g, '\n')

test('rich markdown disables generated controls and configures shiki explicitly', () => {
  assert.match(richMarkdown, /import \{ createCodePlugin \} from '@streamdown\/code'/)
  assert.match(richMarkdown, /import type \{ CustomRendererProps \} from 'streamdown'/)
  assert.match(richMarkdown, /const StreamdownCodeBlock = lazy\(\(\) => import\('streamdown'\)/)
  assert.match(richMarkdown, /const markdownCode = createCodePlugin\(\{[\s\S]*themes: \['github-dark', 'github-dark'\]/)
  assert.match(richMarkdown, /controls=\{false\}/)
  assert.match(richMarkdown, /plugins=\{\{ code: markdownCode, mermaid, math, cjk, renderers: codeRenderers \}\}/)
  assert.doesNotMatch(richMarkdown, /code: \{ copy: true, download: true \}/)
  assert.doesNotMatch(richMarkdown, /table: \{ copy: true, download: true, fullscreen: true \}/)
  assert.doesNotMatch(richMarkdown, /panZoom: true/)
})

test('rich markdown adds source and reference metadata to code block headers', () => {
  assert.match(richMarkdown, /type CodeFenceMetadata = \{/)
  assert.match(richMarkdown, /function parseCodeFenceMetadata\(meta: string \| undefined\): CodeFenceMetadata/)
  assert.match(richMarkdown, /const CODE_RENDERER_LANGUAGES = \[/)
  assert.match(richMarkdown, /function RichCodeBlock\(\{ code, language, meta, isIncomplete \}: CustomRendererProps\)/)
  assert.match(richMarkdown, /data-rich-code-header/)
  assert.match(richMarkdown, /data-rich-code-source/)
  assert.match(richMarkdown, /data-rich-code-reference/)
  assert.match(richMarkdown, /<StreamdownCodeBlock[\s\S]*lineNumbers=\{!metadata\.disableLineNumbers\}/)
})

test('rich markdown wraps tables so wide content scrolls inside the markdown surface', () => {
  assert.doesNotMatch(richMarkdown, /components=\{\{ table:/)
  assert.match(appCss, /\.rich-markdown table/)
  assert.match(appCss, /display: block;/)
  assert.match(appCss, /overflow-x: auto;/)
})

test('rich markdown css preserves highlighting and contains wide blocks', () => {
  assert.match(appCss, /\.rich-markdown \[data-streamdown='code-block-body'\] \[style\*='--sdm-c'\]/)
  assert.match(appCss, /\.rich-markdown \[data-streamdown='code-block-body'\] \[style\*='--sdm-tbg'\]/)
  assert.match(appCss, /\.rich-markdown \[data-streamdown='code-block-actions'\]/)
  assert.match(appCss, /\.rich-markdown \[data-streamdown='code-block'\]/)
  assert.match(appCss, /width: min\(100%, 820px\);/)
  assert.match(appCss, /\.rich-markdown \[data-rich-code-header\]/)
  assert.match(appCss, /\.rich-markdown \[data-rich-code-source\]/)
  assert.match(appCss, /\.rich-markdown \[data-rich-code-reference\]/)
  assert.match(appCss, /\.rich-markdown table/)
  assert.match(appCss, /\.rich-markdown \[data-streamdown='mermaid'\]/)
  assert.match(appCss, /\.rich-markdown \[data-streamdown='mermaid'\] svg/)
})

test('rich markdown normalizes links, blockquotes, and inline code for dark documents', () => {
  assert.match(richMarkdown, /function RichMarkdownLink/)
  assert.match(richMarkdown, /data-rich-link/)
  assert.match(richMarkdown, /target=\{isExternalHref\(href\) \? '_blank' : undefined\}/)
  assert.match(richMarkdown, /function RichMarkdownBlockquote/)
  assert.match(richMarkdown, /data-rich-blockquote/)
  assert.match(richMarkdown, /function RichMarkdownInlineCode/)
  assert.match(richMarkdown, /data-rich-inline-code/)
  assert.match(richMarkdown, /a: RichMarkdownLink/)
  assert.match(richMarkdown, /blockquote: RichMarkdownBlockquote/)
  assert.match(richMarkdown, /inlineCode: RichMarkdownInlineCode/)
  assert.match(appCss, /\.rich-markdown \[data-rich-link\]/)
  assert.match(appCss, /overflow-wrap: anywhere;/)
  assert.match(appCss, /\.rich-markdown \[data-rich-blockquote\]/)
  assert.match(appCss, /\.rich-markdown \[data-rich-inline-code\]/)
})
