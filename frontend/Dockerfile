# Frontend image — Next.js (App Router, P0-05). Multi-stage: install deps →
# build → run a production server with `next start`.
# Node 20 (LTS): Next 15.x supports Node >=18.18; 20 is the safe container floor
# regardless of the host's Node version.

# --- deps: install node_modules (cached unless lockfile changes) -------------
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- builder: produce the optimized .next build -----------------------------
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- runner: minimal production server --------------------------------------
FROM node:20-alpine AS runner
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
