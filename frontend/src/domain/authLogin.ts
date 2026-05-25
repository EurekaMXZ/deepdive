import type { LoginInput } from './auth.ts'

export type EmailLoginDraft = LoginInput & {
  isSubmitting?: boolean
  turnstileRequired?: boolean
  turnstileToken: string | null
}

export type EmailLoginError = 'EMAIL_REQUIRED' | 'PASSWORD_REQUIRED' | 'TURNSTILE_REQUIRED'

export type EmailLoginValidation = {
  canSubmit: boolean
  errors: {
    email?: EmailLoginError
    password?: EmailLoginError
    turnstile?: EmailLoginError
  }
}

export type GitHubLoginUrlInput = {
  apiBaseUrl?: string
  githubAuthUrl?: string
  returnTo?: string
}

export type ReturnToLocationParts = Pick<Location, 'hash' | 'pathname' | 'search'>

export function normalizeEmailLoginInput(input: LoginInput): LoginInput {
  const normalized: LoginInput = {
    email: input.email.trim().toLowerCase(),
    password: input.password,
  }

  if (input.turnstileToken !== undefined) {
    normalized.turnstileToken = input.turnstileToken
  }

  return normalized
}

export function validateEmailLoginDraft(input: EmailLoginDraft): EmailLoginValidation {
  const errors: EmailLoginValidation['errors'] = {}

  if (!input.email.trim()) {
    errors.email = 'EMAIL_REQUIRED'
  }
  if (!input.password) {
    errors.password = 'PASSWORD_REQUIRED'
  }
  if (input.turnstileRequired === true && !input.turnstileToken) {
    errors.turnstile = 'TURNSTILE_REQUIRED'
  }

  return {
    canSubmit: Object.keys(errors).length === 0 && input.isSubmitting !== true,
    errors,
  }
}

export function createGitHubLoginUrl({
  apiBaseUrl = '/api',
  githubAuthUrl,
  returnTo,
}: GitHubLoginUrlInput = {}): string {
  const url = githubAuthUrl ?? joinUrlPath(apiBaseUrl, '/auth/github/start')
  if (!returnTo) {
    return url
  }

  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}redirect_to=${encodeURIComponent(returnTo)}`
}

export function createReturnToPath(location: ReturnToLocationParts): string {
  return `${location.pathname}${location.search}${location.hash}`
}

function joinUrlPath(baseUrl: string, path: string): string {
  const normalizedBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl
  const normalizedPath = path.startsWith('/') ? path : `/${path}`

  if (!normalizedBase) {
    return normalizedPath
  }

  return `${normalizedBase}${normalizedPath}`.replace(/([^:]\/)\/+/g, '$1')
}
