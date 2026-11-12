#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="${PID_DIR:-$ROOT/.run}"

stop_one() {
  local name="$1"
  local pidfile="$PID_DIR/${name}.pid"
  if [[ ! -f "$pidfile" ]]; then
    echo "[skip] ${name}: no pidfile"
    return
  fi
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    # Celery may leave children; give them a moment then force.
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    echo "[ok] stopped ${name} (${pid})"
  else
    echo "[skip] ${name}: not running"
  fi
  rm -f "$pidfile"
}

stop_one web
stop_one worker
stop_one beat

# Catch orphan Celery/runserver from this venv if pidfiles were lost.
pkill -f "$ROOT/venv/bin/celery -A config" 2>/dev/null || true
pkill -f "$ROOT/venv/bin/python manage.py runserver" 2>/dev/null || true

echo "Done."
