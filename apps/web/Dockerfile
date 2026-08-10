FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN corepack enable && corepack prepare pnpm@11.21.0 --activate && pnpm install --frozen-lockfile

COPY apps/web apps/web

EXPOSE 3000
CMD ["pnpm", "--dir", "apps/web", "dev", "--hostname", "0.0.0.0"]
