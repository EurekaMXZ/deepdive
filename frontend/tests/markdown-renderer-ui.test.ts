import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const richMarkdown = readFileSync(resolve('src/features/markdown-renderer/RichMarkdown.tsx'), 'utf8')
const streamingMarkdown = readFileSync(
  resolve('src/features/analysis-preview/StreamingMarkdown.tsx'),
  'utf8',
)
const markdownPreview = readFileSync(
  resolve('src/features/markdown-viewer/MarkdownPreview.tsx'),
  'utf8',
)
const appCss = readFileSync(resolve('src/App.css'), 'utf8').replace(/\r\n/g, '\n')

test('rich markdown enables code highlighting, mermaid, and latex plugins', () => {
  assert.match(richMarkdown, /import \{ code \} from '@streamdown\/code'/)
  assert.match(richMarkdown, /import \{ mermaid \} from '@streamdown\/mermaid'/)
  assert.match(richMarkdown, /import \{ math \} from '@streamdown\/math'/)
  assert.match(richMarkdown, /import \{ cjk \} from '@streamdown\/cjk'/)
  assert.match(richMarkdown, /import 'katex\/dist\/katex\.min\.css'/)
  assert.match(richMarkdown, /import 'streamdown\/styles\.css'/)
  assert.match(richMarkdown, /plugins=\{\{ code, mermaid, math, cjk \}\}/)
  assert.match(richMarkdown, /shikiTheme=\{\['github-dark', 'github-dark'\]\}/)
  assert.match(richMarkdown, /lineNumbers=\{true\}/)
  assert.match(richMarkdown, /controls=\{\{[\s\S]*code: \{ copy: true, download: true \}/)
  assert.match(richMarkdown, /mermaid: \{ fullscreen: true, download: true, copy: true, panZoom: true \}/)
})

test('analysis and document markdown surfaces share the rich renderer', () => {
  assert.match(streamingMarkdown, /import \{ RichMarkdown \} from '..\/markdown-renderer'/)
  assert.match(streamingMarkdown, /<RichMarkdown/)
  assert.doesNotMatch(streamingMarkdown, /import\('streamdown'\)/)

  assert.match(markdownPreview, /import \{ RichMarkdown \} from '..\/markdown-renderer'/)
  assert.match(markdownPreview, /<RichMarkdown/)
  assert.doesNotMatch(markdownPreview, /import\('streamdown'\)/)
})

test('rich markdown styles keep enhanced code, mermaid, and latex readable', () => {
  assert.match(appCss, /\.rich-markdown \.shiki/)
  assert.match(appCss, /\.rich-markdown \[data-streamdown='mermaid'\]/)
  assert.match(appCss, /\.rich-markdown \.katex-display/)
  assert.match(appCss, /\.rich-markdown \[data-streamdown='code-block-body'\]/)
})
