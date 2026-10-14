#!/bin/sh
# Runs the API, the voice worker (when LiveKit is configured) and the web app.
cd /app/backend
# One secret per boot, shared by the API and the voice worker, so only the worker can call /internal/*.
export INTERNAL_TOKEN="${INTERNAL_TOKEN:-$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')}"
uvicorn main:app --host 127.0.0.1 --port 8000 &

if [ -n "$LIVEKIT_URL" ] && [ -n "$LIVEKIT_API_KEY" ]; then
  # Restart the worker if it ever exits (e.g. a transient network drop).
  (while true; do python agent_worker.py start; echo "worker exited, restarting in 5s"; sleep 5; done) &
fi

cd /app/web
PORT="${PORT:-10000}" HOSTNAME=0.0.0.0 exec node server.js
