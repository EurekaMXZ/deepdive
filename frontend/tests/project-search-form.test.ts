import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const projectSearchForm = readFileSync(
  resolve('src/features/project-explorer/ProjectSearchForm.tsx'),
  'utf8',
)

test('project search keeps the input outside dropdown trigger focus management', () => {
  assert.doesNotMatch(projectSearchForm, /DropdownMenu\.Trigger/)
  assert.doesNotMatch(projectSearchForm, /DropdownMenu\.Root/)
  assert.match(projectSearchForm, /onFocus=\{\(\) => setIsSuggestionsOpen\(true\)\}/)
})
