# Closer backend image — runs BOTH the FastAPI API and the LiveKit agent worker.
# Default CMD starts the API (uvicorn). The worker ECS task overrides the command
# to: python agent_worker.py start  (same image, mirrors Converse prod).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: curl for the container health check, build-essential for any
# wheels that compile (asyncpg etc.), libsndfile/ffmpeg for audio handling.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl build-essential ca-certificates libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Pre-download the VAD / turn-detector model weights so calls start instantly.
RUN python agent_worker.py download-files || echo "model download skipped"

EXPOSE 8000

# API by default; worker task definition overrides this command.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
