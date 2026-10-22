# All-in-one image for small/free hosts: web app + API + voice worker in one
# container, one public port. (docker-compose.yml runs them separately.)

# ── 1. Build the web app ─────────────────────────────────────────────────────
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# Clerk's publishable key is baked into the browser bundle at build time.
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=""
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY \
    NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_STANDALONE=1 BACKEND_ORIGIN=http://127.0.0.1:8000
RUN npm run build

# ── 2. Runtime: Python (API + worker) + Node (web) ───────────────────────────
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    LOW_RESOURCE_MODE=true WEBHOOK_BASE_URL=http://127.0.0.1:8000 \
    NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libsndfile1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ ./
# A missing turn-detector download must fail the build rather than silently deploy VAD-only calls.
# The downloader sometimes crashes on exit (a native panic) after the files are already saved, so retry and
# then check the model itself instead of trusting the exit code.
RUN for i in 1 2 3; do python agent_worker.py download-files && break; echo "download-files exited with $?, attempt $i"; done; \
    find /root/.cache/huggingface -path '*turn-detector*' -name '*.onnx' | grep -q . \
    || (echo "turn-detector model missing after download" && exit 1)

COPY --from=web /web/.next/standalone /app/web
COPY --from=web /web/.next/static /app/web/.next/static
COPY --from=web /web/public /app/web/public
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 10000
CMD ["/app/start.sh"]
