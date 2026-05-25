import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMarkdownDocumentTree,
  extractMarkdownHeadings,
  findMarkdownDocument,
  flattenMarkdownDocuments,
  markdownNodesFromDocumentArtifacts,
  markdownNodesFromDocumentList,
} from '../src/domain/markdown.ts'
import type { DocumentArtifactWithContent } from '../src/domain/documents.ts'

const documents = [
  {
    id: 'overview',
    title: 'overview.md',
    markdown: '# Overview\n\nDeepDive analysis.',
  },
  {
    id: 'reports',
    title: 'reports',
    children: [
      {
        id: 'architecture',
        title: 'architecture.md',
        markdown: '# Architecture\n\n## API\n\n### Auth\n\nDetails.',
      },
    ],
  },
]

test('markdown documents can be flattened and found by id', () => {
  assert.deepEqual(
    flattenMarkdownDocuments(documents).map((document) => document.id),
    ['overview', 'reports', 'architecture'],
  )
  assert.equal(findMarkdownDocument(documents, 'architecture')?.title, 'architecture.md')
  assert.equal(findMarkdownDocument(documents, 'missing'), null)
})

test('document tree marks the active branch and depth for rendering', () => {
  assert.deepEqual(
    buildMarkdownDocumentTree(documents, 'architecture').map((node) => ({
      id: node.id,
      depth: node.depth,
      active: node.active,
      expanded: node.expanded,
      children: node.children.map((child) => ({
        id: child.id,
        depth: child.depth,
        active: child.active,
        expanded: child.expanded,
      })),
    })),
    [
      { id: 'overview', depth: 0, active: false, expanded: false, children: [] },
      {
        id: 'reports',
        depth: 0,
        active: false,
        expanded: true,
        children: [{ id: 'architecture', depth: 1, active: true, expanded: false }],
      },
    ],
  )
})

test('markdown headings are extracted without reading fenced code blocks', () => {
  const headings = extractMarkdownHeadings(
    [
      '# Repository Review',
      '',
      '```md',
      '# Not a heading',
      '```',
      '',
      '## API Layer',
      '### Auth & Permissions',
      '#### Ignored Detail',
      '### API Layer',
    ].join('\n'),
  )

  assert.deepEqual(headings, [
    { id: 'repository-review', depth: 1, title: 'Repository Review' },
    { id: 'api-layer', depth: 2, title: 'API Layer' },
    { id: 'auth-permissions', depth: 3, title: 'Auth & Permissions' },
    { id: 'api-layer-2', depth: 3, title: 'API Layer' },
  ])
})

test('document artifacts map to markdown viewer nodes', () => {
  const nodes = markdownNodesFromDocumentArtifacts([
    documentArtifact({
      documentId: 'doc-3',
      title: 'Live Notes',
      status: 'generating',
      content: '# Live',
    }),
    documentArtifact({
      documentId: 'doc-2',
      title: 'API Review',
      status: 'draft',
      content: '# API\n\nDetails.',
    }),
    documentArtifact({
      documentId: 'doc-1',
      title: 'Overview',
      status: 'finalized',
      content: '# Overview',
    }),
  ])

  assert.deepEqual(nodes, [
    {
      id: 'doc-1',
      title: 'Overview',
      path: 'Overview',
      markdown: '# Overview',
      streaming: false,
      children: [],
    },
    {
      id: 'doc-2',
      title: 'API Review',
      path: 'API Review',
      markdown: '# API\n\nDetails.',
      streaming: false,
      children: [],
    },
    {
      id: 'doc-3',
      title: 'Live Notes',
      path: 'Live Notes',
      markdown: '# Live',
      streaming: true,
      children: [],
    },
  ])
})

test('document lists map only the active document content into markdown nodes', () => {
  const nodes = markdownNodesFromDocumentList(
    [
      documentArtifact({
        documentId: 'doc-2',
        title: 'API Review',
        status: 'draft',
      }),
      documentArtifact({
        documentId: 'doc-1',
        title: 'Overview',
        status: 'finalized',
      }),
    ],
    documentArtifact({
      documentId: 'doc-1',
      title: 'Overview',
      status: 'finalized',
      content: '# Overview',
    }),
  )

  assert.deepEqual(nodes, [
    {
      id: 'doc-1',
      title: 'Overview',
      path: 'Overview',
      markdown: '# Overview',
      streaming: false,
      children: [],
    },
    {
      id: 'doc-2',
      title: 'API Review',
      path: 'API Review',
      markdown: undefined,
      streaming: false,
      children: [],
    },
  ])
})

function documentArtifact(
  overrides: Partial<DocumentArtifactWithContent> = {},
): DocumentArtifactWithContent {
  return {
    documentId: 'doc-1',
    analysisId: 'analysis-1',
    agentId: 'agent-1',
    title: 'Overview',
    kind: 'markdown',
    status: 'finalized',
    version: 1,
    contentRef: 'objects/doc-1.md',
    contentHash: 'sha256:doc',
    sizeBytes: 20,
    content: '# Overview',
    ...overrides,
  }
}
