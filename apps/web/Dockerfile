FROM node:22-alpine

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN corepack enable && corepack prepare pnpm@11.21.0 --activate && pnpm install --frozen-lockfile

COPY apps/web apps/web

EXPOSE 3000
CMD ["pnpm", "--dir", "apps/web", "dev", "--hostname", "0.0.0.0"]
