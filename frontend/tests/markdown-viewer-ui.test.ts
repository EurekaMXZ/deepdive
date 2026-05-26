import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const viewer = readFileSync(resolve('src/features/markdown-viewer/MarkdownDocumentViewer.tsx'), 'utf8')
const tree = readFileSync(resolve('src/features/markdown-viewer/MarkdownDocumentTree.tsx'), 'utf8')
const outline = readFileSync(resolve('src/features/markdown-viewer/MarkdownOutline.tsx'), 'utf8')
const preview = readFileSync(resolve('src/features/markdown-viewer/MarkdownPreview.tsx'), 'utf8')
const richMarkdown = readFileSync(resolve('src/features/markdown-renderer/RichMarkdown.tsx'), 'utf8')
const documentsPage = readFileSync(resolve('src/features/documents/AnalysisDocumentsPage.tsx'), 'utf8')
const appCss = readFileSync(resolve('src/App.css'), 'utf8').replace(/\r\n/g, '\n')

test('markdown preview receives outline headings and renders matching heading ids', () => {
  assert.match(viewer, /<MarkdownPreview[\s\S]*headings=\{headings\}/)
  assert.match(preview, /headings\?: MarkdownHeading\[\]/)
  assert.match(preview, /headingIds=\{headings\}/)
  assert.match(richMarkdown, /headingIds\?: MarkdownHeadingId\[\]/)
  assert.match(richMarkdown, /function createHeadingComponent/)
  assert.match(richMarkdown, /components=\{headingComponents\}/)
})

test('markdown viewer exposes separate mobile drawers for documents and outline', () => {
  assert.match(viewer, /useState<'documents' \| 'outline' \| null>/)
  assert.match(viewer, /markdown-viewer__mobile-actions/)
  assert.match(viewer, /aria-label="打开文档树"/)
  assert.match(viewer, /aria-label="打开目录树"/)
  assert.match(viewer, /data-mobile-panel=\{mobilePanel === 'documents' \? 'open' : 'closed'\}/)
  assert.match(viewer, /data-mobile-panel=\{mobilePanel === 'outline' \? 'open' : 'closed'\}/)
  assert.match(viewer, /markdown-viewer__mobile-backdrop/)
})

test('markdown viewer css turns mobile document and outline panels into right drawers', () => {
  assert.match(appCss, /\.markdown-viewer__mobile-actions/)
  assert.match(appCss, /\.markdown-viewer__mobile-button/)
  assert.match(appCss, /\.markdown-viewer__mobile-backdrop/)
  assert.match(appCss, /\.markdown-viewer__sidebar\[data-mobile-panel='open'\]/)
  assert.match(appCss, /\.markdown-viewer__outline\[data-mobile-panel='open'\]/)
  assert.match(appCss, /transform: translateX\(100%\);/)
  assert.match(appCss, /transform: translateX\(0\);/)
})

test('document preview page uses an expandable document tree instead of a flat document list', () => {
  assert.match(documentsPage, /loadDocumentTree\(analysisId\)/)
  assert.match(documentsPage, /markdownNodesFromDocumentTree\(documentTree, content\)/)
  assert.doesNotMatch(documentsPage, /markdownNodesFromDocumentList\(documents, content\)/)
  assert.match(tree, /useState<ReadonlySet<string>>/)
  assert.match(tree, /toggleNodeExpanded/)
  assert.match(tree, /if \(hasChildren\)/)
  assert.doesNotMatch(tree, /disabled=\{node\.selectable === false\}/)
})

test('markdown outline scrolls the preview heading instead of relying on page hash scrolling', () => {
  assert.match(outline, /event\.preventDefault\(\)/)
  assert.match(outline, /onNavigate\?\.\(heading\.id\)/)
  assert.match(viewer, /function handleOutlineNavigate\(headingId: string\)/)
  assert.match(viewer, /document\.getElementById\(headingId\)/)
  assert.match(viewer, /scrollIntoView\(\{[\s\S]*block: 'start'[\s\S]*\}\)/)
  assert.match(viewer, /window\.history\.replaceState/)
})

test('rich markdown assigns heading ids from source lines instead of render order', () => {
  assert.match(richMarkdown, /headingIdByLine/)
  assert.match(richMarkdown, /node\.position\.start\.line/)
  assert.doesNotMatch(richMarkdown, /cursor\.index/)
})
