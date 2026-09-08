web: gunicorn -k uvicorn.workers.UvicornWorker config.asgi:application --bind 0.0.0.0:$PORT
worker: celery -A config worker -Q celery,default,email,video_processing --loglevel=info
beat: celery -A config beat --loglevel=info
