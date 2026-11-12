#!/usr/bin/env bash
# Local process layout mirrors Procfile (web / worker / beat).
# Docker is not required: Redis + Postgres can be Homebrew or managed services.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Load .env into this shell so CELERY_POOL / Redis URLs match Django.
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PYTHON_CMD="${PYTHON_CMD:-venv/bin/python}"
CELERY_CMD="${CELERY_CMD:-venv/bin/celery}"
PID_DIR="${PID_DIR:-$ROOT/.run}"
mkdir -p "$PID_DIR"

# Prefer production prefork. On macOS, fork safety often breaks billiard workers.
# Override with CELERY_POOL=prefork|solo|threads if needed.
if [[ -z "${CELERY_POOL:-}" ]]; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
    CELERY_POOL=threads
  else
    CELERY_POOL=prefork
  fi
fi

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY="${OBJC_DISABLE_INITIALIZE_FORK_SAFETY:-YES}"

QUEUES="${CELERY_QUEUES:-celery,default,email,video_processing}"
LOGLEVEL="${CELERY_LOGLEVEL:-info}"
WEB_BIND="${WEB_BIND:-0.0.0.0:8000}"

echo "=============================================================="
echo " CubixSkill services (Procfile-compatible)"
echo " pool=${CELERY_POOL}  queues=${QUEUES}"
echo "=============================================================="

start_one() {
  local name="$1"
  shift
  local pidfile="$PID_DIR/${name}.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "[skip] ${name} already running (pid $(cat "$pidfile"))"
    return
  fi
  "$@" &
  echo $! >"$pidfile"
  echo "[ok] ${name} pid $(cat "$pidfile")"
}

start_one web "$PYTHON_CMD" manage.py runserver "$WEB_BIND"
start_one worker "$CELERY_CMD" -A config worker \
  -Q "$QUEUES" \
  --loglevel="$LOGLEVEL" \
  --pool="$CELERY_POOL" \
  --prefetch-multiplier="${CELERY_WORKER_PREFETCH_MULTIPLIER:-1}"
start_one beat "$CELERY_CMD" -A config beat --loglevel="$LOGLEVEL"

echo
echo "Web:    http://localhost:8000"
echo "Stop:   scripts/stop-services.sh"
echo "Inspect: $CELERY_CMD -A config inspect ping"
