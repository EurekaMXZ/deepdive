FROM node:24-alpine AS build

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json frontend/package.json

RUN pnpm install --frozen-lockfile

COPY frontend frontend

ARG VITE_API_BASE_URL=/api
ARG VITE_TURNSTILE_ENABLED=false
ARG VITE_TURNSTILE_SITE_KEY=
ARG VITE_GITHUB_AUTH_URL=/api/auth/github/start

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_TURNSTILE_ENABLED=${VITE_TURNSTILE_ENABLED}
ENV VITE_TURNSTILE_SITE_KEY=${VITE_TURNSTILE_SITE_KEY}
ENV VITE_GITHUB_AUTH_URL=${VITE_GITHUB_AUTH_URL}

RUN pnpm --filter @deepdive/frontend build

FROM nginx:1.29-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
