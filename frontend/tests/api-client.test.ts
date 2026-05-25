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

test('listAnalysisSuggestions serializes repository query and maps lightweight analysis results', async () => {
  let requestedUrl = ''
  const client = createDeepDiveApiClient({
    baseUrl: '/api',
    accessToken: 'access-token',
    fetch: async (url) => {
      requestedUrl = String(url)
      return jsonResponse(200, {
        items: [
          {
            analysis_id: 'analysis-1',
            agent_id: 'agent-1',
            snapshot_id: null,
            status: 'completed',
            repository_label: 'openai/codex',
            repository_url: 'https://github.com/openai/codex.git',
            requested_ref: 'main',
            resolved_commit_sha: 'abc123',
            updated_at: '2026-05-24T00:00:00Z',
          },
        ],
      })
    },
  })

  const page = await client.listAnalysisSuggestions({ repositoryQuery: 'openai/codex', limit: 6 })

  assert.equal(requestedUrl, '/api/analysis/suggestions?repository_query=openai%2Fcodex&limit=6')
  assert.equal(page.items[0].analysisId, 'analysis-1')
  assert.equal(page.items[0].repositoryLabel, 'openai/codex')
  assert.equal(page.items[0].repositoryUrl, 'https://github.com/openai/codex.git')
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

test('client sends bearer token to protected analysis requests', async () => {
  const requests: Array<{ url: string; init: RequestInit }> = []
  const client = createDeepDiveApiClient({
    baseUrl: '/api',
    accessToken: () => 'access-token-1',
    fetch: async (url, init = {}) => {
      requests.push({ url: String(url), init })
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    },
  })

  await client.listAnalyses()

  assert.equal(requests[0].url, '/api/analysis')
  assert.equal(headerValue(requests[0].init.headers, 'authorization'), 'Bearer access-token-1')
})

test('auth methods use backend auth routes and normalize token and user fields', async () => {
  const requests: Array<{ url: string; init: RequestInit }> = []
  const client = createDeepDiveApiClient({
    baseUrl: 'http://api.test/',
    fetch: async (url, init = {}) => {
      requests.push({ url: String(url), init })
      if (String(url).endsWith('/auth/register')) {
        return jsonResponse(201, backendUser({ email: 'alice@example.com', display_name: 'Alice' }))
      }
      if (String(url).endsWith('/auth/login')) {
        return jsonResponse(200, {
          access_token: 'access-token',
          refresh_token: 'refresh-token',
          token_type: 'bearer',
          expires_in: 3600,
        })
      }
      if (String(url).endsWith('/auth/me')) {
        return jsonResponse(200, backendUser({ email: 'alice@example.com', display_name: 'Alice' }))
      }
      if (String(url).endsWith('/auth/refresh')) {
        return jsonResponse(200, {
          access_token: 'access-token-2',
          refresh_token: 'refresh-token-2',
          token_type: 'bearer',
          expires_in: 3600,
        })
      }
      return new Response(null, { status: 204 })
    },
  })

  const registered = await client.register({
    email: 'alice@example.com',
    password: 'correct horse battery staple',
    displayName: 'Alice',
  })
  const tokens = await client.login({
    email: 'alice@example.com',
    password: 'correct horse battery staple',
    turnstileToken: 'turnstile-token',
  })
  const me = await client.getCurrentUser()
  const refreshed = await client.refreshToken('refresh-token')
  await client.logout('refresh-token-2')

  assert.equal(requests[0].url, 'http://api.test/auth/register')
  assert.equal(
    requests[0].init.body,
    JSON.stringify({
      email: 'alice@example.com',
      password: 'correct horse battery staple',
      display_name: 'Alice',
    }),
  )
  assert.equal(tokens.accessToken, 'access-token')
  assert.equal(
    requests[1].init.body,
    JSON.stringify({
      email: 'alice@example.com',
      password: 'correct horse battery staple',
      turnstile_token: 'turnstile-token',
    }),
  )
  assert.equal(refreshed.refreshToken, 'refresh-token-2')
  assert.equal(registered.displayName, 'Alice')
  assert.deepEqual(me.permissions, ['analysis:create', 'analysis:read'])
  assert.equal(requests[4].url, 'http://api.test/auth/logout')
  assert.equal(requests[4].init.body, JSON.stringify({ refresh_token: 'refresh-token-2' }))
})

test('user and role methods match backend management API contracts', async () => {
  const requests: Array<{ url: string; init: RequestInit }> = []
  const client = createDeepDiveApiClient({
    baseUrl: '/api',
    accessToken: 'admin-token',
    fetch: async (url, init = {}) => {
      requests.push({ url: String(url), init })
      if (String(url) === '/api/users') {
        if (init.method === 'POST') {
          return jsonResponse(
            201,
            backendUser({ id: 'user-2', email: 'member@example.com', display_name: 'Member' }),
          )
        }
        return jsonResponse(200, { items: [backendUser({ email: 'admin@example.com' })] })
      }
      if (String(url).endsWith('/users/user-2/roles')) {
        return jsonResponse(200, {
          roles: [backendRole({ id: 'role-1', name: 'viewer', permissions: [] })],
        })
      }
      if (String(url).endsWith('/roles')) {
        return jsonResponse(200, {
          items: [backendRole({ id: 'role-1', name: 'viewer', permissions: [] })],
        })
      }
      if (String(url).endsWith('/permissions')) {
        return jsonResponse(200, {
          items: [{ id: 'permission-1', name: 'analysis:read', description: 'Read analyses' }],
        })
      }
      if (String(url).endsWith('/users/user-2')) {
        return jsonResponse(
          200,
          backendUser({ id: 'user-2', email: 'member@example.com', display_name: 'Renamed' }),
        )
      }
      return jsonResponse(200, {
        roles: [backendRole({ id: 'role-1', name: 'viewer', permissions: [] })],
      })
    },
  })

  const users = await client.listUsers()
  const created = await client.createUser({
    email: 'member@example.com',
    password: 'correct horse battery staple',
    displayName: 'Member',
    roleNames: ['viewer'],
  })
  const updated = await client.updateUser('user-2', { displayName: 'Renamed', isActive: false })
  const roles = await client.listRoles()
  const permissions = await client.listPermissions()
  const assigned = await client.updateUserRoles('user-2', ['role-1'])

  assert.equal(users.items[0].email, 'admin@example.com')
  assert.equal(created.id, 'user-2')
  assert.equal(updated.displayName, 'Renamed')
  assert.equal(roles.items[0].name, 'viewer')
  assert.equal(permissions.items[0].name, 'analysis:read')
  assert.equal(assigned.roles[0].id, 'role-1')
  assert.equal(headerValue(requests[0].init.headers, 'authorization'), 'Bearer admin-token')
  assert.equal(
    requests[1].init.body,
    JSON.stringify({
      email: 'member@example.com',
      password: 'correct horse battery staple',
      display_name: 'Member',
      role_names: ['viewer'],
    }),
  )
  assert.equal(
    requests[2].init.body,
    JSON.stringify({
      display_name: 'Renamed',
      is_active: false,
    }),
  )
  assert.equal(requests[5].init.body, JSON.stringify({ role_ids: ['role-1'] }))
})

test('document methods match backend analysis document API contracts', async () => {
  const requests: Array<{ url: string; init: RequestInit }> = []
  const client = createDeepDiveApiClient({
    baseUrl: '/api',
    accessToken: 'docs-token',
    fetch: async (url, init = {}) => {
      requests.push({ url: String(url), init })
      if (String(url).endsWith('/content')) {
        return jsonResponse(200, backendDocument({ content: '# Review\n\nFindings.' }))
      }
      if (String(url).endsWith('/revisions')) {
        return jsonResponse(200, {
          items: [
            {
              revision_id: 'revision-1',
              document_id: 'document-1',
              version: 1,
              tool_call_id: 'tool-call-1',
              operation: 'create',
              content_ref: 'objects/revision-1.md',
              content_hash: 'sha256:revision',
              size_bytes: 20,
              created_at: '2026-05-24T00:00:00Z',
            },
          ],
        })
      }
      if (String(url).endsWith('/document-1')) {
        return jsonResponse(200, backendDocument())
      }
      return jsonResponse(200, { items: [backendDocument()] })
    },
  })

  const documents = await client.listAnalysisDocuments('analysis-1')
  const document = await client.getAnalysisDocument('analysis-1', 'document-1')
  const content = await client.getAnalysisDocumentContent('analysis-1', 'document-1')
  const revisions = await client.listAnalysisDocumentRevisions('analysis-1', 'document-1')

  assert.equal(requests[0].url, '/api/analysis/analysis-1/documents')
  assert.equal(requests[1].url, '/api/analysis/analysis-1/documents/document-1')
  assert.equal(requests[2].url, '/api/analysis/analysis-1/documents/document-1/content')
  assert.equal(requests[3].url, '/api/analysis/analysis-1/documents/document-1/revisions')
  assert.equal(headerValue(requests[0].init.headers, 'authorization'), 'Bearer docs-token')
  assert.equal(documents.items[0].documentId, 'document-1')
  assert.equal(document.title, 'Repository review')
  assert.equal(content.content, '# Review\n\nFindings.')
  assert.equal(revisions.items[0].toolCallId, 'tool-call-1')
})

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function headerValue(headers: HeadersInit | undefined, key: string): string | null {
  return new Headers(headers).get(key)
}

function backendUser(overrides: Record<string, unknown> = {}) {
  return {
    id: 'user-1',
    tenant_id: 'tenant-1',
    email: 'user@example.com',
    display_name: null,
    is_active: true,
    created_at: '2026-05-24T00:00:00Z',
    updated_at: '2026-05-24T00:00:00Z',
    roles: [backendRole()],
    permissions: ['analysis:create', 'analysis:read'],
    ...overrides,
  }
}

function backendRole(overrides: Record<string, unknown> = {}) {
  return {
    id: 'role-1',
    name: 'admin',
    description: 'Admin',
    permissions: [{ id: 'permission-1', name: 'analysis:read', description: 'Read analyses' }],
    ...overrides,
  }
}

function backendDocument(overrides: Record<string, unknown> = {}) {
  return {
    document_id: 'document-1',
    analysis_id: 'analysis-1',
    agent_id: 'agent-1',
    title: 'Repository review',
    kind: 'markdown',
    status: 'draft',
    version: 1,
    content_ref: 'objects/document-1.md',
    content_hash: 'sha256:document',
    size_bytes: 20,
    ...overrides,
  }
}
