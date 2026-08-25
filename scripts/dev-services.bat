@echo off
echo ==============================================================
echo  CubixSkill Production-Ready Background Services Launcher
echo ==============================================================
echo.

set PYTHON_CMD=venv\Scripts\python.exe
set CELERY_CMD=venv\Scripts\celery.exe

echo [1/4] Starting Django Dev Web Server on http://localhost:8000 ...
start "Django Server" %PYTHON_CMD% manage.py runserver 0.0.0.0:8000

echo [2/4] Starting Celery Email & General Worker ...
start "Celery Email Worker" %CELERY_CMD% -A config worker -l info -Q email,default -P solo

echo [3/4] Starting Celery Media Video Transcoder Worker ...
start "Celery Media Worker" %CELERY_CMD% -A config worker -l info -Q video_processing -c 2 -P solo

echo [4/4] Starting Celery Beat Scheduler ...
start "Celery Beat" %CELERY_CMD% -A config beat -l info

echo.
echo All CubixSkill backend services started successfully!
echo Django: http://localhost:8000
echo Control Panel: http://localhost:8000/
