export type Permission = {
  id: string
  name: string
  description: string
}

export type Role = {
  id: string
  name: string
  description: string
  permissions: Permission[]
}

export type User = {
  id: string
  tenantId: string
  email: string
  displayName: string | null
  isActive: boolean
  createdAt: string
  updatedAt: string
  roles: Role[]
  permissions: string[]
}

export type TokenPair = {
  accessToken: string
  refreshToken: string
  tokenType: string
  expiresIn: number
}

export type RegisterInput = {
  email: string
  password: string
  displayName?: string | null
}

export type LoginInput = {
  email: string
  password: string
  turnstileToken?: string | null
}

export type CreateUserInput = {
  email: string
  password: string
  displayName?: string | null
  roleNames?: string[]
}

export type UpdateUserInput = {
  displayName?: string | null
  isActive?: boolean
}

export type UserListPage = {
  items: User[]
}

export type RoleListPage = {
  items: Role[]
}

export type PermissionListPage = {
  items: Permission[]
}

export type UserRoles = {
  roles: Role[]
}

export type TokenStore = {
  getAccessToken(): string | null
  getBearerToken(): string | null
  getRefreshToken(): string | null
  setTokens(tokens: TokenPair): void
  clear(): void
}

export type PermissionChecker = {
  can(permission: string): boolean
  canAny(permissions: string[]): boolean
  canAll(permissions: string[]): boolean
  hasRole(roleName: string): boolean
}

export type AuthSessionState =
  | {
      status: 'anonymous'
      user: null
      tokens: null
      permissions: PermissionChecker
    }
  | {
      status: 'authenticated'
      user: User
      tokens: TokenPair
      permissions: PermissionChecker
    }

export type AuthSession = {
  getState(): AuthSessionState
  getAccessToken(): string | null
  login(input: LoginInput): Promise<AuthSessionState>
  register(input: RegisterInput): Promise<User>
  restore(): Promise<AuthSessionState>
  refresh(): Promise<AuthSessionState>
  logout(): Promise<AuthSessionState>
}

export type AuthSessionClient = {
  register(input: RegisterInput): Promise<User>
  login(input: LoginInput): Promise<TokenPair>
  refreshToken(refreshToken: string): Promise<TokenPair>
  logout(refreshToken: string): Promise<void>
  getCurrentUser(): Promise<User>
}

export type AuthSessionOptions = {
  client: AuthSessionClient
  initialState?: AuthSessionState
  tokenStore?: TokenStore
}

const EMPTY_PERMISSION_CHECKER: PermissionChecker = createPermissionChecker(null)

export function createMemoryTokenStore(initialTokens?: TokenPair | null): TokenStore {
  let tokens = initialTokens ?? null

  return {
    getAccessToken() {
      return tokens?.accessToken ?? null
    },
    getBearerToken() {
      return tokens ? formatBearerToken(tokens) : null
    },
    getRefreshToken() {
      return tokens?.refreshToken ?? null
    },
    setTokens(nextTokens) {
      tokens = nextTokens
    },
    clear() {
      tokens = null
    },
  }
}

export function createBrowserTokenStore(
  storage: Pick<Storage, 'getItem' | 'removeItem' | 'setItem'>,
  options: {
    accessTokenKey?: string
    bearerTokenKey?: string
    refreshTokenKey?: string
  } = {},
): TokenStore {
  const accessTokenKey = options.accessTokenKey ?? 'deepdive.access_token'
  const bearerTokenKey = options.bearerTokenKey ?? 'deepdive.bearer_token'
  const refreshTokenKey = options.refreshTokenKey ?? 'deepdive.refresh_token'

  return {
    getAccessToken() {
      return storage.getItem(accessTokenKey)
    },
    getBearerToken() {
      return storage.getItem(bearerTokenKey)
    },
    getRefreshToken() {
      return storage.getItem(refreshTokenKey)
    },
    setTokens(tokens) {
      storage.setItem(accessTokenKey, tokens.accessToken)
      storage.setItem(bearerTokenKey, formatBearerToken(tokens))
      storage.setItem(refreshTokenKey, tokens.refreshToken)
    },
    clear() {
      storage.removeItem(accessTokenKey)
      storage.removeItem(bearerTokenKey)
      storage.removeItem(refreshTokenKey)
    },
  }
}

export function createPermissionChecker(user: User | null): PermissionChecker {
  const permissions = new Set(user?.permissions ?? [])
  const roles = new Set(user?.roles.map((role) => role.name) ?? [])

  return {
    can(permission) {
      return permissions.has(permission)
    },
    canAny(nextPermissions) {
      return nextPermissions.some((permission) => permissions.has(permission))
    },
    canAll(nextPermissions) {
      return nextPermissions.every((permission) => permissions.has(permission))
    },
    hasRole(roleName) {
      return roles.has(roleName)
    },
  }
}

export function createAnonymousAuthSessionState(): AuthSessionState {
  return {
    status: 'anonymous',
    user: null,
    tokens: null,
    permissions: EMPTY_PERMISSION_CHECKER,
  }
}

export function createAuthenticatedAuthSessionState(
  user: User,
  tokens: TokenPair,
): AuthSessionState {
  return {
    status: 'authenticated',
    user,
    tokens,
    permissions: createPermissionChecker(user),
  }
}

function formatBearerToken(tokens: TokenPair): string {
  const tokenType = tokens.tokenType.trim() || 'Bearer'
  const normalizedTokenType = tokenType.toLowerCase() === 'bearer' ? 'Bearer' : tokenType
  return `${normalizedTokenType} ${tokens.accessToken}`
}

export function createAuthSession({
  client,
  initialState = createAnonymousAuthSessionState(),
  tokenStore = createMemoryTokenStore(initialState.tokens),
}: AuthSessionOptions): AuthSession {
  let state = initialState

  function setAnonymous() {
    tokenStore.clear()
    state = createAnonymousAuthSessionState()
    return state
  }

  async function authenticate(tokens: TokenPair) {
    tokenStore.setTokens(tokens)
    const user = await client.getCurrentUser()
    state = createAuthenticatedAuthSessionState(user, tokens)
    return state
  }

  async function refresh() {
    const refreshToken = tokenStore.getRefreshToken()
    if (!refreshToken) {
      return setAnonymous()
    }

    try {
      return await authenticate(await client.refreshToken(refreshToken))
    } catch (error) {
      setAnonymous()
      throw error
    }
  }

  async function restoreWithCurrentAccessToken() {
    const accessToken = tokenStore.getAccessToken()
    const refreshToken = tokenStore.getRefreshToken()
    if (!accessToken) {
      return null
    }

    const user = await client.getCurrentUser()
    state = createAuthenticatedAuthSessionState(user, {
      accessToken,
      refreshToken: refreshToken ?? '',
      tokenType: 'bearer',
      expiresIn: 0,
    })
    return state
  }

  return {
    getState() {
      return state
    },
    getAccessToken() {
      return tokenStore.getAccessToken()
    },
    async login(input) {
      return authenticate(await client.login(input))
    },
    async register(input) {
      return client.register(input)
    },
    async restore() {
      try {
        const restored = await restoreWithCurrentAccessToken()
        if (restored) {
          return restored
        }
      } catch {
        // The stored access token is stale; try the refresh token before clearing local auth.
      }

      try {
        return await refresh()
      } catch {
        return state
      }
    },
    refresh,
    async logout() {
      const refreshToken = tokenStore.getRefreshToken()
      try {
        if (refreshToken) {
          await client.logout(refreshToken)
        }
      } finally {
        setAnonymous()
      }
      return state
    },
  }
}
