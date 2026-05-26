import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const loginDialog = readFileSync(resolve('src/features/auth/LoginDialog.tsx'), 'utf8')

test('github login uses the Simple Icons GitHub brand mark', () => {
  assert.match(loginDialog, /import \{ siGithub \} from 'simple-icons'/)
  assert.match(loginDialog, /<SimpleIconMark icon=\{siGithub\}/)
  assert.match(loginDialog, /viewBox="0 0 24 24"/)
  assert.match(loginDialog, /<path d=\{icon\.path\}/)
  assert.doesNotMatch(loginDialog, /GitBranch/)
})
