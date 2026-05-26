import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMarkdownDocumentTree,
  extractMarkdownHeadings,
  findMarkdownDocument,
  flattenMarkdownDocuments,
  markdownNodesFromDocumentArtifacts,
  markdownNodesFromDocumentList,
  markdownNodesFromDocumentTree,
} from '../src/domain/markdown.ts'
import type { DocumentArtifactWithContent, DocumentTreeNode } from '../src/domain/documents.ts'

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
    { id: 'repository-review', depth: 1, line: 1, title: 'Repository Review' },
    { id: 'api-layer', depth: 2, line: 7, title: 'API Layer' },
    { id: 'auth-permissions', depth: 3, line: 8, title: 'Auth & Permissions' },
    { id: 'api-layer-2', depth: 3, line: 10, title: 'API Layer' },
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

test('document tree maps folders and documents into nested markdown viewer nodes', () => {
  const nodes = markdownNodesFromDocumentTree(
    [
      documentTreeNode({
        nodeId: 'folder-backend',
        nodeType: 'folder',
        documentId: null,
        title: 'Backend',
        path: 'backend',
        children: [
          documentTreeNode({
            nodeId: 'node-auth',
            documentId: 'doc-auth',
            title: 'Authentication',
            path: 'backend/authentication',
            status: 'finalized',
          }),
          documentTreeNode({
            nodeId: 'folder-workers',
            nodeType: 'folder',
            documentId: null,
            title: 'Workers',
            path: 'backend/workers',
            children: [
              documentTreeNode({
                nodeId: 'node-agent',
                documentId: 'doc-agent',
                title: 'Agent Worker',
                path: 'backend/workers/agent-worker',
                status: 'generating',
              }),
            ],
          }),
        ],
      }),
    ],
    documentArtifact({
      documentId: 'doc-auth',
      title: 'Authentication',
      status: 'finalized',
      content: '# Auth',
    }),
  )

  assert.deepEqual(nodes, [
    {
      id: 'folder-backend',
      documentId: null,
      title: 'Backend',
      path: 'backend',
      selectable: false,
      streaming: false,
      children: [
        {
          id: 'doc-auth',
          documentId: 'doc-auth',
          title: 'Authentication',
          path: 'backend/authentication',
          markdown: '# Auth',
          selectable: true,
          streaming: false,
          children: [],
        },
        {
          id: 'folder-workers',
          documentId: null,
          title: 'Workers',
          path: 'backend/workers',
          selectable: false,
          streaming: false,
          children: [
            {
              id: 'doc-agent',
              documentId: 'doc-agent',
              title: 'Agent Worker',
              path: 'backend/workers/agent-worker',
              markdown: undefined,
              selectable: true,
              streaming: true,
              children: [],
            },
          ],
        },
      ],
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

function documentTreeNode(overrides: Partial<DocumentTreeNode> = {}): DocumentTreeNode {
  return {
    nodeId: 'node-1',
    nodeType: 'document',
    documentId: 'doc-1',
    title: 'Overview',
    slug: 'overview',
    path: 'overview',
    focusArea: null,
    sortOrder: 0,
    status: 'draft',
    version: 1,
    sectionCount: 1,
    children: [],
    ...overrides,
  }
}
