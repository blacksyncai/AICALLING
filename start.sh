#!/bin/sh
# Runs the API, the voice worker (when LiveKit is configured) and the web app.
#
# Deploys: Railway sends SIGTERM to the old instance. The worker then stops taking new calls and lets the calls
# in progress finish (LiveKit drain), while the API stays up so their results are saved; only then do the API and
# web app stop. Set RAILWAY_DEPLOYMENT_DRAINING_SECONDS (e.g. 900) so Railway waits that long before force-killing.
cd /app/backend
# One secret per boot, shared by the API and the voice worker, so only the worker can call /internal/*.
export INTERNAL_TOKEN="${INTERNAL_TOKEN:-$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')}"
uvicorn main:app --host 127.0.0.1 --port 8000 &
API_PID=$!

WORKER_PID=""
if [ -n "$LIVEKIT_URL" ] && [ -n "$LIVEKIT_API_KEY" ]; then
  (
    STOP=0
    CHILD=""
    trap 'STOP=1; [ -n "$CHILD" ] && kill -TERM "$CHILD" 2>/dev/null' TERM
    # Restart the worker if it ever exits on its own (e.g. a transient network drop).
    while [ "$STOP" = 0 ]; do
      python agent_worker.py start &
      CHILD=$!
      wait "$CHILD"
      while kill -0 "$CHILD" 2>/dev/null; do wait "$CHILD"; done  # still draining after a signal
      if [ "$STOP" = 0 ]; then echo "worker exited, restarting in 5s"; sleep 5; fi
    done
  ) &
  WORKER_PID=$!
fi

cd /app/web
PORT="${PORT:-10000}" HOSTNAME=0.0.0.0 node server.js &
WEB_PID=$!

shutdown() {
  trap '' TERM INT
  echo "shutting down: letting calls in progress finish"
  if [ -n "$WORKER_PID" ]; then
    kill -TERM "$WORKER_PID" 2>/dev/null
    wait "$WORKER_PID" 2>/dev/null
  fi
  kill -TERM "$WEB_PID" "$API_PID" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap shutdown TERM INT

# The web app is the service's front door: if it stops, the instance stops (Railway restarts it).
wait "$WEB_PID"
