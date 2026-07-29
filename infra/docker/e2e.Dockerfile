# v1.61.1-noble, manifest-list digest sha256:5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48
FROM mcr.microsoft.com/playwright@sha256:5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48

ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH CI=true
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY tests/e2e/package.json tests/e2e/package.json
RUN pnpm install --filter e2e... --frozen-lockfile
COPY tests/e2e tests/e2e
COPY apps/api/tests/fixtures/imports apps/api/tests/fixtures/imports
WORKDIR /app/tests/e2e
CMD ["pnpm", "exec", "playwright", "test", "-c", "fresh-install.playwright.config.ts"]
