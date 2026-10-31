FROM node:24-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

FROM base AS deps
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

FROM base AS development
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
RUN chown -R node:node /app
USER node
CMD ["npx", "next", "dev", "--hostname", "0.0.0.0", "--port", "3000"]

FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
RUN npm run build

FROM base AS production
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
USER node
CMD ["node", "server.js"]
