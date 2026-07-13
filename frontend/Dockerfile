# Frontend image — Next.js (App Router, P0-05). Multi-stage: install deps →
# build → run a production server with `next start`.
# Node 22 (active LTS): Next 15.x supports Node >=18.18; 22 is the current
# supported container floor, kept in lockstep with frontend-ci's node-version.

# --- deps: install node_modules (cached unless lockfile changes) -------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- builder: produce the optimized .next build -----------------------------
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NB (SEC-04): INTERNAL_API_URL is no longer a build input. The old same-origin
# /api/* rewrite froze it into the build manifest; the BFF Route Handlers (app/api/*)
# that replaced it read INTERNAL_API_URL at REQUEST time (Node runtime), so it is
# supplied as a runtime env var (docker-compose `environment:`; defaults to
# http://localhost:8000 via lib/apiProxy.ts when unset). Nothing here reads it.
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- runner: minimal production server --------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

EXPOSE 3000

# `next start` serves the production build on $PORT.
CMD ["npm", "run", "start"]
