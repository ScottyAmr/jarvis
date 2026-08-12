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
  lsof -ti:"$BACKEND_PORT"  2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti:"$FRONTEND_PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

# --- start both servers ------------------------------------------------------
echo "Starting backend  (port $BACKEND_PORT)..."
./.venv/bin/python server.py 2>&1 | sed 's/^/[backend]  /' &

echo "Starting frontend (port $FRONTEND_PORT)..."
( cd frontend && npm run dev ) 2>&1 | sed 's/^/[frontend] /' &

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

# Watch both ports; if either server stops listening, tear the other down too.
while true; do
  sleep 2
  if ! lsof -ti:"$BACKEND_PORT" >/dev/null 2>&1; then
    echo "[launcher] backend stopped."; cleanup
  fi
  if ! lsof -ti:"$FRONTEND_PORT" >/dev/null 2>&1; then
    echo "[launcher] frontend stopped."; cleanup
  fi
done
