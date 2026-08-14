import os
from config.wsgi import application as wsgi_app

# Expose wsgi application for production servers (Gunicorn, Uvicorn, Waitress)
app = wsgi_app
