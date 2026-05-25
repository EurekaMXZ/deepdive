import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createGitHubLoginUrl,
  createReturnToPath,
  normalizeEmailLoginInput,
  validateEmailLoginDraft,
} from '../src/domain/authLogin.ts'

test('email login requires credentials and a turnstile token when turnstile is enabled', () => {
  const empty = validateEmailLoginDraft({
    email: '',
    password: '',
    turnstileRequired: true,
    turnstileToken: null,
  })

  assert.equal(empty.canSubmit, false)
  assert.equal(empty.errors.email, 'EMAIL_REQUIRED')
  assert.equal(empty.errors.password, 'PASSWORD_REQUIRED')
  assert.equal(empty.errors.turnstile, 'TURNSTILE_REQUIRED')

  const verified = validateEmailLoginDraft({
    email: 'alice@example.com',
    password: 'correct horse battery staple',
    turnstileRequired: true,
    turnstileToken: 'turnstile-token',
  })

  assert.equal(verified.canSubmit, true)
  assert.deepEqual(verified.errors, {})
})

test('email login does not require a turnstile token when turnstile is disabled', () => {
  const validation = validateEmailLoginDraft({
    email: 'alice@example.com',
    password: 'correct horse battery staple',
    turnstileRequired: false,
    turnstileToken: null,
  })

  assert.equal(validation.canSubmit, true)
  assert.deepEqual(validation.errors, {})
})

test('email login cannot submit while an authentication request is in flight', () => {
  const validation = validateEmailLoginDraft({
    email: 'alice@example.com',
    password: 'correct horse battery staple',
    turnstileToken: 'turnstile-token',
    isSubmitting: true,
  })

  assert.equal(validation.canSubmit, false)
})

test('email login input trims and lowercases the email without changing the password', () => {
  assert.deepEqual(
    normalizeEmailLoginInput({
      email: ' Alice@Example.COM ',
      password: ' correct horse battery staple ',
    }),
    {
      email: 'alice@example.com',
      password: ' correct horse battery staple ',
    },
  )
})

test('github login url targets the auth provider route and preserves return path', () => {
  assert.equal(
    createGitHubLoginUrl({
      apiBaseUrl: '/api',
      returnTo: '/workspace?repo=openai%2Fcodex',
    }),
    '/api/auth/github/start?redirect_to=%2Fworkspace%3Frepo%3Dopenai%252Fcodex',
  )

  assert.equal(
    createGitHubLoginUrl({
      githubAuthUrl: 'https://auth.deepdive.test/oauth/github?prompt=login',
      returnTo: '/',
    }),
    'https://auth.deepdive.test/oauth/github?prompt=login&redirect_to=%2F',
  )
})

test('return path is built from the current browser location parts', () => {
  assert.equal(
    createReturnToPath({
      pathname: '/workspace',
      search: '?repo=openai%2Fcodex',
      hash: '#runs',
    }),
    '/workspace?repo=openai%2Fcodex#runs',
  )
})
