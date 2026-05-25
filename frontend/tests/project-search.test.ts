import assert from 'node:assert/strict'
import test from 'node:test'

import type { AnalysisSuggestion } from '../src/domain/analysis.ts'
import { documentHrefForAnalysisSuggestion } from '../src/domain/analysisSubmissions.ts'
import { getTimeAwareGreeting } from '../src/domain/projectGreeting.ts'
import { normalizeRepositoryQuery } from '../src/domain/projectSearch.ts'

test('normalizes a shorthand repository query into an HTTPS Git URL', () => {
  assert.equal(
    normalizeRepositoryQuery(' openai/codex '),
    'https://github.com/openai/codex.git',
  )
})

test('preserves full Git repository URLs while trimming whitespace', () => {
  assert.equal(
    normalizeRepositoryQuery(' https://github.com/openai/codex.git '),
    'https://github.com/openai/codex.git',
  )
})

test('analysis suggestions link to document preview pages', () => {
  assert.equal(
    documentHrefForAnalysisSuggestion(
      suggestion({
        analysisId: 'analysis-1',
        status: 'completed',
      }),
    ),
    '/analysis/analysis-1/documents',
  )
  assert.equal(documentHrefForAnalysisSuggestion(suggestion({ status: 'running' })), null)
})

test('project explorer greeting follows local day period', () => {
  assert.equal(getTimeAwareGreeting(new Date('2026-05-26T08:00:00')), '早上好，今天你想探索什么？')
  assert.equal(getTimeAwareGreeting(new Date('2026-05-26T13:00:00')), '下午好，今天你想探索什么？')
  assert.equal(getTimeAwareGreeting(new Date('2026-05-26T21:00:00')), '晚上好，今天你想探索什么？')
})

function suggestion(overrides: Partial<AnalysisSuggestion> = {}): AnalysisSuggestion {
  return {
    analysisId: 'analysis-1',
    agentId: 'agent-1',
    snapshotId: null,
    status: 'completed',
    repositoryLabel: 'openai/codex',
    repositoryUrl: 'https://github.com/openai/codex.git',
    requestedRef: 'main',
    resolvedCommitSha: null,
    updatedAt: '2026-05-24T00:00:00Z',
    ...overrides,
  }
}
