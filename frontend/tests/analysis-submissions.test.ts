import assert from 'node:assert/strict'
import test from 'node:test'

import type { Analysis } from '../src/domain/analysis.ts'
import {
  canCancelAnalysisStatus,
  createAnalysisSubmissionRows,
  documentHrefForAnalysisRow,
  normalizeCreateAnalysisDraft,
  validateCreateAnalysisDraft,
} from '../src/domain/analysisSubmissions.ts'

test('analysis submission rows are sorted by update time and expose status labels', () => {
  const rows = createAnalysisSubmissionRows([
    analysis({
      analysisId: 'analysis-old',
      repositoryUrl: 'https://github.com/openai/codex.git',
      status: 'completed',
      updatedAt: '2026-05-23T10:00:00Z',
    }),
    analysis({
      analysisId: 'analysis-new',
      repositoryUrl: 'https://github.com/vercel/next.js.git',
      status: 'running',
      updatedAt: '2026-05-24T10:00:00Z',
    }),
  ])

  assert.deepEqual(
    rows.map((row) => row.analysisId),
    ['analysis-new', 'analysis-old'],
  )
  assert.deepEqual(rows[0], {
    analysisId: 'analysis-new',
    repositoryLabel: 'vercel/next.js',
    repositoryUrl: 'https://github.com/vercel/next.js.git',
    requestedRef: 'main',
    status: 'running',
    statusLabel: '分析中',
    statusPhase: 'running',
    canCancel: true,
    updatedAt: '2026-05-24T10:00:00Z',
    updatedAtLabel: '2026-05-24 10:00',
    analysisHref: '/analysis/analysis-new',
    documentsHref: null,
  })
})

test('completed analysis rows expose document page links', () => {
  const rows = createAnalysisSubmissionRows([
    analysis({
      analysisId: 'analysis-complete',
      status: 'completed',
    }),
    analysis({
      analysisId: 'analysis-running',
      status: 'running',
    }),
  ])

  assert.equal(documentHrefForAnalysisRow(rows[0]), '/analysis/analysis-complete/documents')
  assert.equal(rows[0].documentsHref, '/analysis/analysis-complete/documents')
  assert.equal(rows[0].canCancel, false)
  assert.equal(documentHrefForAnalysisRow(rows[1]), null)
  assert.equal(rows[1].documentsHref, null)
  assert.equal(rows[1].canCancel, true)
})

test('analysis cancellation is only available for active non-cancelling statuses', () => {
  assert.equal(canCancelAnalysisStatus('queued'), true)
  assert.equal(canCancelAnalysisStatus('snapshotting'), true)
  assert.equal(canCancelAnalysisStatus('running'), true)
  assert.equal(canCancelAnalysisStatus('calling_model'), true)
  assert.equal(canCancelAnalysisStatus('waiting_tool'), true)
  assert.equal(canCancelAnalysisStatus('cancelling'), false)
  assert.equal(canCancelAnalysisStatus('completed'), false)
  assert.equal(canCancelAnalysisStatus('failed'), false)
  assert.equal(canCancelAnalysisStatus('cancelled'), false)
})

test('create analysis draft normalizes github shorthand and defaults ref to main', () => {
  assert.deepEqual(
    normalizeCreateAnalysisDraft({
      repository: ' openai/codex ',
      ref: ' ',
    }),
    {
      repositoryUrl: 'https://github.com/openai/codex.git',
      ref: 'main',
    },
  )
})

test('create analysis draft validation requires a repository', () => {
  assert.deepEqual(validateCreateAnalysisDraft({ repository: '', ref: 'main' }), {
    canSubmit: false,
    repositoryError: '请输入仓库地址',
  })
  assert.deepEqual(validateCreateAnalysisDraft({ repository: 'openai/codex', ref: '' }), {
    canSubmit: true,
    repositoryError: null,
  })
})

function analysis(overrides: Partial<Analysis> = {}): Analysis {
  return {
    analysisId: 'analysis-1',
    agentId: 'agent-1',
    snapshotId: null,
    status: 'queued',
    repositoryUrl: 'https://github.com/example/project.git',
    requestedRef: 'main',
    resolvedCommitSha: null,
    errorCode: null,
    errorMessage: null,
    createdAt: '2026-05-24T09:00:00Z',
    updatedAt: '2026-05-24T09:00:00Z',
    ...overrides,
  }
}
