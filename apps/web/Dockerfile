# syntax=docker/dockerfile:1.7
# ============================================================
#  Nuxt 3 frontend — multi-stage Dockerfile
#  Targets: dev (npm install + dev server) | runtime (built .output)
# ============================================================

# Node 22: eslint-flat-config-utils (@nuxt/eslint) требует Object.groupBy (Node 21+)
ARG NODE_VERSION=22

# ---------- Stage: base ----------
FROM node:${NODE_VERSION}-alpine AS base
WORKDIR /app

# ---------- Stage: dev (hot-reload) ----------
FROM base AS dev
# Зависимости ставятся при старте контейнера (volume с исходниками).
# См. docker-compose: command: sh -c "npm install && npm run dev ..."
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

# ---------- Stage: build (production build) ----------
FROM base AS build
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---------- Stage: runtime (prod) ----------
FROM node:${NODE_VERSION}-alpine AS runtime
WORKDIR /app
# HOST/PORT: явный bind 0.0.0.0:3000 для nitro (иначе может слушать только localhost)
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000
COPY --from=build /app/.output ./.output
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
