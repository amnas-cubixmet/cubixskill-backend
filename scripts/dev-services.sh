#!/usr/bin/env bash

echo "=============================================================="
echo " CubixSkill Production-Ready Background Services Launcher"
echo "=============================================================="

PYTHON_CMD="venv/bin/python"
CELERY_CMD="venv/bin/celery"

echo "[1/4] Starting Django Dev Web Server on http://localhost:8000 ..."
$PYTHON_CMD manage.py runserver 0.0.0.0:8000 &

echo "[2/4] Starting Celery Email & General Worker ..."
$CELERY_CMD -A config worker -l info -Q email,default &

echo "[3/4] Starting Celery Media Video Transcoder Worker ..."
$CELERY_CMD -A config worker -l info -Q video_processing -c 2 &

echo "[4/4] Starting Celery Beat Scheduler ..."
$CELERY_CMD -A config beat -l info &

echo "All CubixSkill backend background services started in background."
