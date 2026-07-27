# Playwright's explicitly versioned upstream image supplies the matching browser runtime.
FROM mcr.microsoft.com/playwright:v1.61.1-noble

ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH CI=true
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY tests/e2e/package.json tests/e2e/package.json
RUN pnpm install --filter e2e... --frozen-lockfile
COPY tests/e2e tests/e2e
WORKDIR /app/tests/e2e
CMD ["pnpm", "exec", "playwright", "test", "-c", "fresh-install.playwright.config.ts"]
