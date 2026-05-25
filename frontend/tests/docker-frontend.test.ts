import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const compose = readFileSync(resolve('..', 'docker-compose.yml'), 'utf8')
const dockerignore = readFileSync(resolve('..', '.dockerignore'), 'utf8')
const frontendDockerfilePath = resolve('Dockerfile')
const nginxConfigPath = resolve('nginx.conf')

test('docker compose defines a production frontend service served by nginx', () => {
  assert.match(compose, /^\s{2}frontend:\n/m)
  assert.match(compose, /container_name:\s+deepdive-frontend/)
  assert.match(compose, /dockerfile:\s+frontend\/Dockerfile/)
  assert.match(compose, /FRONTEND_PORT:-5173/)
  assert.match(compose, /VITE_API_BASE_URL:\s+\$\{VITE_API_BASE_URL:-\/api\}/)
  assert.match(compose, /VITE_TURNSTILE_ENABLED:\s+\$\{VITE_TURNSTILE_ENABLED:-false\}/)
  assert.match(compose, /VITE_TURNSTILE_SITE_KEY:\s+\$\{VITE_TURNSTILE_SITE_KEY:-\}/)
  assert.match(compose, /api:\n\s+condition:\s+service_started/)
})

test('frontend dockerfile builds the vite workspace and serves dist from nginx', () => {
  assert.equal(existsSync(frontendDockerfilePath), true)

  const dockerfile = readFileSync(frontendDockerfilePath, 'utf8')
  assert.match(dockerfile, /FROM node:[\w.-]+ AS build/)
  assert.match(dockerfile, /corepack enable/)
  assert.match(dockerfile, /COPY package\.json pnpm-lock\.yaml pnpm-workspace\.yaml \.\//)
  assert.match(dockerfile, /COPY frontend\/package\.json frontend\/package\.json/)
  assert.match(dockerfile, /pnpm install --frozen-lockfile/)
  assert.match(dockerfile, /pnpm --filter @deepdive\/frontend build/)
  assert.match(dockerfile, /FROM nginx:[\w.-]+/)
  assert.match(dockerfile, /COPY frontend\/nginx\.conf \/etc\/nginx\/conf\.d\/default\.conf/)
  assert.match(dockerfile, /COPY --from=build \/app\/frontend\/dist \/usr\/share\/nginx\/html/)
})

test('frontend nginx config supports spa routing and backend api streaming proxy', () => {
  assert.equal(existsSync(nginxConfigPath), true)

  const nginxConfig = readFileSync(nginxConfigPath, 'utf8')
  assert.match(nginxConfig, /listen 80;/)
  assert.match(nginxConfig, /root \/usr\/share\/nginx\/html;/)
  assert.match(nginxConfig, /location \/api\//)
  assert.match(nginxConfig, /proxy_pass http:\/\/api:8000\/api\//)
  assert.match(nginxConfig, /proxy_http_version 1\.1;/)
  assert.match(nginxConfig, /proxy_buffering off;/)
  assert.match(nginxConfig, /proxy_cache off;/)
  assert.match(nginxConfig, /try_files \$uri \$uri\/ \/index\.html;/)
})

test('docker ignore keeps frontend sources available for the frontend build context', () => {
  assert.doesNotMatch(dockerignore, /^frontend$/m)
  assert.match(dockerignore, /^frontend\/node_modules$/m)
  assert.match(dockerignore, /^frontend\/dist$/m)
})
