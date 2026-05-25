import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createAuthSession,
  createBrowserTokenStore,
  createMemoryTokenStore,
  createPermissionChecker,
  type AuthSessionState,
} from '../src/domain/auth.ts'
import type { AuthSessionClient } from '../src/domain/auth.ts'
import type { TokenPair, User } from '../src/domain/auth.ts'

test('memory token store saves, reads, and clears auth tokens', () => {
  const store = createMemoryTokenStore()

  assert.equal(store.getAccessToken(), null)
  assert.equal(store.getBearerToken(), null)
  assert.equal(store.getRefreshToken(), null)

  store.setTokens(tokenPair('access-1', 'refresh-1'))

  assert.equal(store.getAccessToken(), 'access-1')
  assert.equal(store.getBearerToken(), 'Bearer access-1')
  assert.equal(store.getRefreshToken(), 'refresh-1')

  store.clear()

  assert.equal(store.getAccessToken(), null)
  assert.equal(store.getBearerToken(), null)
  assert.equal(store.getRefreshToken(), null)
})

test('browser token store persists bearer token in localStorage', () => {
  const storage = createStorageStub()
  const store = createBrowserTokenStore(storage)

  store.setTokens(tokenPair('access-1', 'refresh-1'))

  assert.equal(storage.getItem('deepdive.access_token'), 'access-1')
  assert.equal(storage.getItem('deepdive.refresh_token'), 'refresh-1')
  assert.equal(storage.getItem('deepdive.bearer_token'), 'Bearer access-1')
  assert.equal(store.getAccessToken(), 'access-1')
  assert.equal(store.getBearerToken(), 'Bearer access-1')
  assert.equal(store.getRefreshToken(), 'refresh-1')

  store.clear()

  assert.equal(storage.getItem('deepdive.access_token'), null)
  assert.equal(storage.getItem('deepdive.refresh_token'), null)
  assert.equal(storage.getItem('deepdive.bearer_token'), null)
  assert.equal(store.getBearerToken(), null)
})

test('permission checker supports any, all, and role checks', () => {
  const checker = createPermissionChecker(
    user({
      permissions: ['analysis:create', 'analysis:read', 'documents:read'],
      roles: [{ name: 'admin' }],
    }),
  )

  assert.equal(checker.can('analysis:create'), true)
  assert.equal(checker.can('users:write'), false)
  assert.equal(checker.canAny(['users:write', 'documents:read']), true)
  assert.equal(checker.canAll(['analysis:create', 'analysis:read']), true)
  assert.equal(checker.canAll(['analysis:create', 'users:write']), false)
  assert.equal(checker.hasRole('admin'), true)
  assert.equal(checker.hasRole('viewer'), false)
})

test('auth session logs in, persists tokens, loads current user, and exposes permissions', async () => {
  const calls: string[] = []
  const store = createMemoryTokenStore()
  const session = createAuthSession({
    client: authClient({
      login: async () => {
        calls.push('login')
        return tokenPair('access-1', 'refresh-1')
      },
      getCurrentUser: async () => {
        calls.push('me')
        return user({ permissions: ['analysis:create'] })
      },
    }),
    tokenStore: store,
  })

  const state = await session.login({
    email: 'alice@example.com',
    password: 'correct horse battery staple',
  })

  assert.deepEqual(calls, ['login', 'me'])
  assert.equal(store.getAccessToken(), 'access-1')
  assert.equal(store.getRefreshToken(), 'refresh-1')
  assert.equal(state.status, 'authenticated')
  assert.equal(state.user?.email, 'alice@example.com')
  assert.equal(session.getState().permissions.can('analysis:create'), true)
})

test('auth session refreshes with stored refresh token and clears invalid sessions', async () => {
  const store = createMemoryTokenStore()
  store.setTokens(tokenPair('expired-access', 'refresh-1'))
  const session = createAuthSession({
    client: authClient({
      refreshToken: async (refreshToken) => {
        assert.equal(refreshToken, 'refresh-1')
        return tokenPair('access-2', 'refresh-2')
      },
      getCurrentUser: async () => user({ email: 'refreshed@example.com' }),
    }),
    tokenStore: store,
  })

  const state = await session.refresh()

  assert.equal(state.status, 'authenticated')
  assert.equal(state.user?.email, 'refreshed@example.com')
  assert.equal(store.getAccessToken(), 'access-2')
  assert.equal(store.getRefreshToken(), 'refresh-2')

  store.setTokens(tokenPair('expired-access', 'invalid-refresh'))
  const failingSession = createAuthSession({
    client: authClient({
      getCurrentUser: async () => {
        throw new Error('expired access token')
      },
      refreshToken: async () => {
        throw new Error('invalid refresh token')
      },
    }),
    tokenStore: store,
  })

  const failed = await failingSession.restore()

  assert.equal(failed.status, 'anonymous')
  assert.equal(store.getAccessToken(), null)
  assert.equal(store.getRefreshToken(), null)
})

test('auth session restores from a stored access token before refreshing', async () => {
  const calls: string[] = []
  const store = createMemoryTokenStore()
  store.setTokens(tokenPair('valid-access', 'refresh-1'))
  const session = createAuthSession({
    client: authClient({
      refreshToken: async () => {
        calls.push('refresh')
        return tokenPair('access-2', 'refresh-2')
      },
      getCurrentUser: async () => {
        calls.push('me')
        return user({ email: 'stored@example.com', permissions: ['analysis:read'] })
      },
    }),
    tokenStore: store,
  })

  const state = await session.restore()

  assert.deepEqual(calls, ['me'])
  assert.equal(state.status, 'authenticated')
  assert.equal(state.user?.email, 'stored@example.com')
  assert.equal(store.getAccessToken(), 'valid-access')
  assert.equal(store.getRefreshToken(), 'refresh-1')
  assert.equal(session.getState().permissions.can('analysis:read'), true)
})

test('auth session falls back to refresh when stored access token is invalid', async () => {
  const calls: string[] = []
  const store = createMemoryTokenStore()
  store.setTokens(tokenPair('expired-access', 'refresh-1'))
  const session = createAuthSession({
    client: authClient({
      refreshToken: async (refreshToken) => {
        calls.push(`refresh:${refreshToken}`)
        return tokenPair('access-2', 'refresh-2')
      },
      getCurrentUser: async () => {
        calls.push('me')
        if (calls.length === 1) {
          throw new Error('expired access token')
        }
        return user({ email: 'refreshed@example.com' })
      },
    }),
    tokenStore: store,
  })

  const state = await session.restore()

  assert.deepEqual(calls, ['me', 'refresh:refresh-1', 'me'])
  assert.equal(state.status, 'authenticated')
  assert.equal(state.user?.email, 'refreshed@example.com')
  assert.equal(store.getAccessToken(), 'access-2')
  assert.equal(store.getRefreshToken(), 'refresh-2')
})

test('auth session logout calls backend when refresh token exists and clears local state', async () => {
  const store = createMemoryTokenStore()
  store.setTokens(tokenPair('access-1', 'refresh-1'))
  let loggedOutRefreshToken = ''
  const session = createAuthSession({
    client: authClient({
      logout: async (refreshToken) => {
        loggedOutRefreshToken = refreshToken
      },
    }),
    initialState: authenticatedState(),
    tokenStore: store,
  })

  const state = await session.logout()

  assert.equal(loggedOutRefreshToken, 'refresh-1')
  assert.equal(state.status, 'anonymous')
  assert.equal(store.getAccessToken(), null)
  assert.equal(session.getState().permissions.can('analysis:read'), false)
})

function authClient(overrides: Partial<AuthSessionClient>): AuthSessionClient {
  return {
    register: async () => user(),
    login: async () => tokenPair(),
    refreshToken: async () => tokenPair(),
    logout: async () => {},
    getCurrentUser: async () => user(),
    ...overrides,
  }
}

function tokenPair(accessToken = 'access-token', refreshToken = 'refresh-token'): TokenPair {
  return {
    accessToken,
    refreshToken,
    tokenType: 'bearer',
    expiresIn: 3600,
  }
}

function createStorageStub(): Pick<Storage, 'getItem' | 'removeItem' | 'setItem'> {
  const values = new Map<string, string>()

  return {
    getItem(key) {
      return values.get(key) ?? null
    },
    removeItem(key) {
      values.delete(key)
    },
    setItem(key, value) {
      values.set(key, value)
    },
  }
}

function user(overrides: Partial<User> & { roles?: Array<{ name: string }> } = {}): User {
  return {
    id: 'user-1',
    tenantId: 'tenant-1',
    email: 'alice@example.com',
    displayName: 'Alice',
    isActive: true,
    createdAt: '2026-05-24T00:00:00Z',
    updatedAt: '2026-05-24T00:00:00Z',
    roles: (overrides.roles ?? []).map((role, index) => ({
      id: `role-${index + 1}`,
      name: role.name,
      description: role.name,
      permissions: [],
    })),
    permissions: overrides.permissions ?? [],
    ...overrides,
  }
}

function authenticatedState(): AuthSessionState {
  const currentUser = user({ permissions: ['analysis:read'] })
  return {
    status: 'authenticated',
    user: currentUser,
    tokens: tokenPair('access-1', 'refresh-1'),
    permissions: createPermissionChecker(currentUser),
  }
}
