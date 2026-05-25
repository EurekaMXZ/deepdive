import assert from 'node:assert/strict'
import test from 'node:test'

import { isAnalysisThreadAtBottom } from '../src/features/analysis-preview/analysisScroll.ts'

test('analysis stream sticks to bottom only when the thread is already near the bottom', () => {
  assert.equal(
    isAnalysisThreadAtBottom({
      clientHeight: 500,
      scrollHeight: 1200,
      scrollTop: 684,
    }),
    true,
  )

  assert.equal(
    isAnalysisThreadAtBottom({
      clientHeight: 500,
      scrollHeight: 1200,
      scrollTop: 620,
    }),
    false,
  )
})
