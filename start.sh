#!/bin/sh
# Runs the API, the voice worker (when LiveKit is configured) and the web app.
#
# Deploys: Railway sends SIGTERM to the old instance. The worker then stops taking new calls and lets the calls
# in progress finish (LiveKit drain), while the API stays up so their results are saved; only then do the API and
# web app stop. railway.json's drainingSeconds makes Railway wait that long before force-killing.
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

# Open the public port only once the API answers, so a deploy never sends visitors to an instance whose API is
# still starting (that showed as ~30 s of errors after every deploy). Gives up waiting after 2 minutes.
i=0
while [ "$i" -lt 120 ]; do
  python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" 2>/dev/null && break
  kill -0 "$API_PID" 2>/dev/null || break
  i=$((i + 1))
  sleep 1
done

cd /app/web
PORT="${PORT:-10000}" HOSTNAME=0.0.0.0 node server.js &
WEB_PID=$!

shutdown() {
  trap '' TERM INT
  echo "shutting down: letting calls in progress finish"
  # Stop placing new calls here (the new instance dials); the API stays up to save the results of live calls.
  python -c "import urllib.request,os; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/internal/quiesce', method='POST', headers={'X-Internal-Token': os.environ.get('INTERNAL_TOKEN','')}), timeout=5)" 2>/dev/null || true
  T0=$(date +%s)
  if [ -n "$WORKER_PID" ]; then
    kill -TERM "$WORKER_PID" 2>/dev/null
    wait "$WORKER_PID" 2>/dev/null
  fi
  # Keep answering for at least 45 s: the new instance may still be starting, and visitors mid-request finish here.
  while [ $(( $(date +%s) - T0 )) -lt "${SHUTDOWN_LINGER_SECONDS:-45}" ]; do sleep 1; done
  kill -TERM "$WEB_PID" "$API_PID" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap shutdown TERM INT

# The web app is the service's front door: if it stops, the instance stops (Railway restarts it).
wait "$WEB_PID"
