FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
ENV NEXT_TELEMETRY_DISABLED=1

RUN corepack enable

WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/shared-schemas/package.json packages/shared-schemas/package.json
RUN pnpm install --filter web... --frozen-lockfile

COPY apps/web apps/web
COPY packages/shared-schemas packages/shared-schemas
RUN chown -R node:node /app/apps/web /app/packages/shared-schemas

WORKDIR /app/apps/web

USER node

EXPOSE 3000

CMD ["/app/apps/web/node_modules/.bin/next", "dev", "--hostname", "0.0.0.0"]
