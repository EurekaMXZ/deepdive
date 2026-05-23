import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiError, createDeepDiveApiClient } from '../src/api/client.ts'

test('createAnalysis posts backend field names and returns the created analysis', async () => {
  const requests: Array<{ url: string; init: RequestInit }> = []
  const client = createDeepDiveApiClient({
    baseUrl: 'http://api.test/',
    fetch: async (url, init = {}) => {
      requests.push({ url: String(url), init })
      return new Response(
        JSON.stringify({
          analysis_id: '019e505e-df2b-7e6f-9a5e-141aa98f59da',
          agent_id: '019e505e-e55b-7c2f-9f62-141aa98f59db',
          snapshot_id: null,
          status: 'queued',
          created_at: '2026-05-24T00:00:00Z',
        }),
        { status: 201, headers: { 'content-type': 'application/json' } },
      )
    },
  })

  const created = await client.createAnalysis({
    repositoryUrl: 'https://github.com/example/project.git',
    ref: 'main',
  })

  assert.equal(requests[0].url, 'http://api.test/analysis')
  assert.equal(requests[0].init.method, 'POST')
  assert.equal(
    requests[0].init.body,
    JSON.stringify({
      repository_url: 'https://github.com/example/project.git',
      ref: 'main',
    }),
  )
  assert.equal(created.analysisId, '019e505e-df2b-7e6f-9a5e-141aa98f59da')
  assert.equal(created.status, 'queued')
})

test('listAnalyses serializes filters and pagination cursor', async () => {
  let requestedUrl = ''
  const client = createDeepDiveApiClient({
    baseUrl: '/api',
    fetch: async (url) => {
      requestedUrl = String(url)
      return new Response(JSON.stringify({ items: [], next_cursor: 'next' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    },
  })

  const page = await client.listAnalyses({
    status: 'running',
    limit: 25,
    cursor: 'abc',
  })

  assert.equal(requestedUrl, '/api/analysis?status=running&limit=25&cursor=abc')
  assert.deepEqual(page, { items: [], nextCursor: 'next' })
})

test('request failures throw ApiError with backend error envelope', async () => {
  const client = createDeepDiveApiClient({
    baseUrl: '/api',
    fetch: async () =>
      new Response(
        JSON.stringify({
          error: {
            code: 'ANALYSIS_NOT_FOUND',
            message: 'Analysis does not exist.',
            request_id: '019e505e-df2b-7e6f-9a5e-141aa98f59da',
          },
        }),
        { status: 404, headers: { 'content-type': 'application/json' } },
      ),
  })

  await assert.rejects(
    client.getAnalysis('019e505e-df2b-7e6f-9a5e-141aa98f59da'),
    (error) => {
      assert.equal(error instanceof ApiError, true)
      assert.equal((error as ApiError).code, 'ANALYSIS_NOT_FOUND')
      assert.equal((error as ApiError).requestId, '019e505e-df2b-7e6f-9a5e-141aa98f59da')
      return true
    },
  )
})
