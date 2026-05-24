import assert from 'node:assert/strict'
import test from 'node:test'

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
