FROM node:22.23.3-bookworm-slim AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22.23.3-bookworm-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_BASE_URL=/api
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22.23.3-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN groupadd --gid 10001 visaautomatic \
    && useradd --uid 10001 --gid visaautomatic --create-home --shell /usr/sbin/nologin visaautomatic

COPY --from=builder --chown=visaautomatic:visaautomatic /app/.next/standalone ./
COPY --from=builder --chown=visaautomatic:visaautomatic /app/.next/static ./.next/static

USER visaautomatic
EXPOSE 3000
CMD ["node", "server.js"]
