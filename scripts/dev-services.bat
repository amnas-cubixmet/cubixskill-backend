@echo off
REM Local process layout mirrors Procfile (web / worker / beat).
REM Docker is not required when Redis + Postgres are available locally.

set PYTHON_CMD=venv\Scripts\python.exe
set CELERY_CMD=venv\Scripts\celery.exe
set CELERY_POOL=solo
if defined CELERY_POOL_OVERRIDE set CELERY_POOL=%CELERY_POOL_OVERRIDE%
set QUEUES=celery,default,email,video_processing

echo ==============================================================
echo  CubixSkill services (Procfile-compatible)
echo  pool=%CELERY_POOL%  queues=%QUEUES%
echo ==============================================================

start "CubixSkill Web" %PYTHON_CMD% manage.py runserver 0.0.0.0:8000
start "CubixSkill Worker" %CELERY_CMD% -A config worker -Q %QUEUES% --loglevel=info --pool=%CELERY_POOL% --prefetch-multiplier=1
start "CubixSkill Beat" %CELERY_CMD% -A config beat --loglevel=info

echo.
echo Web: http://localhost:8000
echo Same shape as Procfile worker/beat processes.
