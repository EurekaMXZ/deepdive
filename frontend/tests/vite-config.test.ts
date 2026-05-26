import assert from 'node:assert/strict'
import test from 'node:test'

import viteConfig from '../vite.config.ts'

test('dev server proxies frontend api paths to the backend runtime', () => {
  const config = typeof viteConfig === 'function' ? viteConfig({ command: 'serve', mode: 'development' }) : viteConfig
  const apiProxy = config.server?.proxy?.['/api']

  assert.equal(typeof apiProxy, 'object')
  assert.equal(apiProxy?.target, 'http://127.0.0.1:8000')
  assert.equal(apiProxy?.changeOrigin, true)
  assert.equal(apiProxy?.rewrite?.('/api/auth/login') ?? '/api/auth/login', '/api/auth/login')
})
