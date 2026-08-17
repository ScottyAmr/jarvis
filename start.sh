#!/usr/bin/env bash
#
# JARVIS launcher — starts the backend and frontend together.
# Run it from anywhere:   ~/Developer/jarvis/start.sh
# Stop everything:        press Ctrl+C in this window.
#
set -euo pipefail

# Always operate from the repo this script lives in, regardless of $PWD.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_PORT=8340
FRONTEND_PORT=5173
WATCHDOG_PID=""

echo "JARVIS launcher — $ROOT"

# --- sanity checks -----------------------------------------------------------
if [ ! -x "./.venv/bin/python" ]; then
  echo "ERROR: ./.venv/bin/python not found. Set up the virtualenv first." >&2
  exit 1
fi
if [ ! -d "./frontend/node_modules" ]; then
  echo "ERROR: frontend/node_modules missing. Run 'cd frontend && npm install' first." >&2
  exit 1
fi

# --- free the backend port if a previous run got stuck -----------------------
if lsof -ti:"$BACKEND_PORT" >/dev/null 2>&1; then
  echo "Port $BACKEND_PORT busy — clearing a stale server..."
  lsof -ti:"$BACKEND_PORT" | xargs kill 2>/dev/null || true
  sleep 1
fi

# --- teardown ----------------------------------------------------------------
# Kill by PORT rather than PID: reliable even though each server runs behind a
# log-prefixing pipe (and npm spawns child processes of its own).
DONE=0
cleanup() {
  [ "$DONE" = "1" ] && return
  DONE=1
  echo ""
  echo "Stopping JARVIS..."
  if [ -n "${WATCHDOG_PID:-}" ]; then
    kill "$WATCHDOG_PID" 2>/dev/null || true
  fi
  lsof -ti:"$BACKEND_PORT"  2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti:"$FRONTEND_PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

# --- start both servers ------------------------------------------------------
start_backend() {
  # Clear any lingering process on the port (e.g. a reload-watcher subprocess
  # left behind by a SIGKILL) before relaunching — avoids "Address already in use".
  lsof -ti:"$BACKEND_PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  sleep 1
  echo "Starting backend  (port $BACKEND_PORT)..."
  ./.venv/bin/python server.py --reload 2>&1 | sed 's/^/[backend]  /' &
}
start_frontend() {
  echo "Starting frontend (port $FRONTEND_PORT)..."
  ( cd frontend && npm run dev ) 2>&1 | sed 's/^/[frontend] /' &
}
start_watchdog() {
  echo "Starting watchdog..."
  ./.venv/bin/python watchdog.py \
    --health-url "http://127.0.0.1:$BACKEND_PORT/api/health" \
    --restart-url "http://127.0.0.1:$BACKEND_PORT/api/restart" \
    --port "$BACKEND_PORT" &
  WATCHDOG_PID=$!
}

start_backend
start_frontend
start_watchdog

echo ""
echo "======================================================"
echo "  JARVIS is starting up..."
echo "  Chrome will open automatically when it's ready."
echo "  Press Ctrl+C here to stop both servers."
echo "======================================================"
echo ""

# Wait for BOTH servers to be listening (up to ~25s), then open Chrome for them.
for _ in $(seq 1 25); do
  if lsof -ti:"$BACKEND_PORT" >/dev/null 2>&1 && lsof -ti:"$FRONTEND_PORT" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if lsof -ti:"$FRONTEND_PORT" >/dev/null 2>&1; then
  sleep 1  # let Vite finish its first compile
  echo "[launcher] Opening Chrome at http://localhost:$FRONTEND_PORT ..."
  open -a "Google Chrome" "http://localhost:$FRONTEND_PORT" 2>/dev/null \
    || open "http://localhost:$FRONTEND_PORT" 2>/dev/null || true
fi

# Watch both ports; if either dies, restart just that one (the frontend
# already reconnects its WebSocket with backoff once the backend comes back
# — see frontend/src/ws.ts — so a backend blip no longer needs to take the
# whole stack down). Capped at 5 restarts per service within a 10-minute
# window so a genuinely broken start (crashes immediately every time)
# reports itself instead of spinning forever.
BACKEND_RESTARTS=0
FRONTEND_RESTARTS=0
WINDOW_START=$(date +%s)
RESTART_CAP=5
RESTART_WINDOW_SECONDS=600

maybe_reset_window() {
  local now elapsed
  now=$(date +%s)
  elapsed=$(( now - WINDOW_START ))
  if [ "$elapsed" -gt "$RESTART_WINDOW_SECONDS" ]; then
    WINDOW_START=$now
    BACKEND_RESTARTS=0
    FRONTEND_RESTARTS=0
  fi
}

while true; do
  sleep 2
  maybe_reset_window

  if ! lsof -ti:"$BACKEND_PORT" >/dev/null 2>&1; then
    if [ "$BACKEND_RESTARTS" -ge "$RESTART_CAP" ]; then
      echo "[launcher] backend died $RESTART_CAP times in ${RESTART_WINDOW_SECONDS}s — giving up on auto-restart."
      echo "[launcher] check data/jarvis.log for the actual error, fix it, then re-run ./start.sh."
      cleanup
    fi
    BACKEND_RESTARTS=$((BACKEND_RESTARTS + 1))
    echo "[launcher] backend stopped (restart $BACKEND_RESTARTS/$RESTART_CAP) — restarting it..."
    start_backend
  fi

  if ! lsof -ti:"$FRONTEND_PORT" >/dev/null 2>&1; then
    if [ "$FRONTEND_RESTARTS" -ge "$RESTART_CAP" ]; then
      echo "[launcher] frontend died $RESTART_CAP times in ${RESTART_WINDOW_SECONDS}s — giving up on auto-restart."
      cleanup
    fi
    FRONTEND_RESTARTS=$((FRONTEND_RESTARTS + 1))
    echo "[launcher] frontend stopped (restart $FRONTEND_RESTARTS/$RESTART_CAP) — restarting it..."
    start_frontend
  fi
done
