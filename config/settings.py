import os
import sys
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers, default_methods
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

# Add apps directory to sys.path cleanly
APPS_DIR = BASE_DIR / 'apps'
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-cubixskill-production-backend-secret-key-change-in-prod')

DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 't')

if not DEBUG and SECRET_KEY.startswith('django-insecure-'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("SECRET_KEY environment variable must be set to a secure secret when DEBUG is False.")

raw_allowed_hosts = os.getenv('ALLOWED_HOSTS', '')
if raw_allowed_hosts:
    ALLOWED_HOSTS = [h.strip() for h in raw_allowed_hosts.split(',') if h.strip()]
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]'] if DEBUG else []

if not DEBUG and '*' in ALLOWED_HOSTS:
    ALLOWED_HOSTS = [h for h in ALLOWED_HOSTS if h != '*']

AUTH_USER_MODEL = 'users_roles.User'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'daphne',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'channels',

    'core',
    'academy',
    'authentication',
    'users_roles',
    'features',
    'plans_entitlements',
    'courses',
    'modules',
    'lessons',
    'storage',
    'students',
    'enrollments',
    'learning_progress',
    'certificates',
    'live_classes',
    'discussions_chat',
    'leads',
    'payments',
    'fees',
    'credits',
    'website',
    'notifications',
    'emails',
    'analytics_reports',
    'audit_logs',
    'settings',
    'control_panel',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'control_panel.context_processors.control_panel_permissions',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database Configuration (Environment Driven: PostgreSQL vs SQLite fallback)
if os.getenv('DATABASE_URL'):
    try:
        import dj_database_url
        DATABASES = {
            'default': dj_database_url.config(default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
        }
    except ImportError:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
elif os.getenv('DB_NAME') and os.getenv('USE_POSTGRES', 'False').lower() in ('true', '1', 't'):
    DATABASES = {
        'default': {
            'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
            'NAME': os.getenv('DB_NAME'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'authentication.authentication.CookieJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Redis & Channels Configuration
REDIS_URL = os.getenv('REDIS_URL', os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0'))
USE_REDIS_CHANNELS = os.getenv('USE_REDIS_CHANNELS', str(not DEBUG)).lower() in ('true', '1', 't')

if USE_REDIS_CHANNELS:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [REDIS_URL],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# Storage Backend Selector (local vs s3/minio)
STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'local' if DEBUG else 's3').lower()

# MinIO / S3 Object Storage Settings
MINIO_ENDPOINT_URL = os.getenv('MINIO_ENDPOINT_URL', 'http://localhost:9000')
MINIO_EXTERNAL_ENDPOINT_URL = os.getenv('MINIO_EXTERNAL_ENDPOINT_URL', os.getenv('MINIO_ENDPOINT_URL', 'http://localhost:9000'))
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'minioadmin')
MINIO_STORAGE_BUCKET_NAME = os.getenv('MINIO_STORAGE_BUCKET_NAME', 'cubixskill-media')
MINIO_REGION_NAME = os.getenv('MINIO_REGION_NAME', 'us-east-1')
MINIO_USE_SSL = os.getenv('MINIO_USE_SSL', 'False').lower() in ('true', '1', 't')

import mimetypes

mimetypes.add_type('application/vnd.apple.mpegurl', '.m3u8')
mimetypes.add_type('video/mp2t', '.ts')

MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'

IMAGE_MAX_SIZE_MB = 10
DOCUMENT_MAX_SIZE_MB = 25
VIDEO_MAX_SIZE_MB = 500
AUDIO_MAX_SIZE_MB = 100

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Payment Gateway Configuration (Razorpay Only)
PAYMENT_PROVIDER = os.getenv('PAYMENT_PROVIDER', 'razorpay').lower()
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')
RAZORPAY_CURRENCY = os.getenv('RAZORPAY_CURRENCY', 'INR')

# Email Configuration (Supports SMTP App Password via EMAIL_HOST_PASSWORD)
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend' if not DEBUG else 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@cubixskill.com')

# FFmpeg & FFprobe Configuration
FFMPEG_BINARY = os.getenv('FFMPEG_BINARY', None)
FFPROBE_BINARY = os.getenv('FFPROBE_BINARY', None)

# CORS Configuration
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False
cors_origins_env = os.getenv('CORS_ALLOWED_ORIGINS', '')
if cors_origins_env:
    CORS_ALLOWED_ORIGINS = [origin.strip() for origin in cors_origins_env.split(',') if origin.strip()]
else:
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:5174",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5173",
    ]

CORS_ALLOW_HEADERS = list(default_headers) + [
    'x-portal',
]

CORS_ALLOW_METHODS = list(default_methods)

csrf_trusted_env = os.getenv('CSRF_TRUSTED_ORIGINS', '')
if csrf_trusted_env:
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in csrf_trusted_env.split(',') if origin.strip()]
else:
    CSRF_TRUSTED_ORIGINS = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ]

# Cookie Configuration for JWT Auth
AUTH_COOKIE_SECURE = os.getenv('AUTH_COOKIE_SECURE', str(not DEBUG)).lower() in ('true', '1', 't')
AUTH_COOKIE_SAMESITE = os.getenv('AUTH_COOKIE_SAMESITE', 'Lax')
AUTH_COOKIE_PATH = os.getenv('AUTH_COOKIE_PATH', '/')
AUTH_COOKIE_DOMAIN = os.getenv('AUTH_COOKIE_DOMAIN', None)

# HTTPS Security Header Configuration
if not DEBUG:
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 't')
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() in ('true', '1', 't')
    CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'True').lower() in ('true', '1', 't')
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True').lower() in ('true', '1', 't')
    SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'True').lower() in ('true', '1', 't')
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    if os.getenv('USE_SECURE_PROXY_HEADER', 'False').lower() in ('true', '1', 't'):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Frontend URL Configuration
FRONTEND_ACADEMY_URL = os.getenv('FRONTEND_ACADEMY_URL', 'http://localhost:5173')
STUDENT_PUBLIC_URL = os.getenv('STUDENT_PUBLIC_URL', 'http://localhost:5174').rstrip('/')

# Authentication Settings
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'

# --------------------------------------------------------------
# Celery & Redis Task Queue Configuration
# --------------------------------------------------------------
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/1')

CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 3
CELERY_RESULT_BACKEND_MAX_RETRIES = 3
CELERY_RESULT_EXPIRES = 86400  # 24 hours

CELERY_TASK_ROUTES = {
    'emails.tasks.*': {'queue': 'default'},
    'authentication.tasks.*': {'queue': 'default'},
    'storage.meter_due_storage_usage': {'queue': 'default'},
    'storage.debit_due_storage_billing_cycles': {'queue': 'default'},
    'storage.tasks.process_video_transcoding_task': {'queue': 'video_processing'},
    'certificates.tasks.*': {'queue': 'default'},
    'enrollments.tasks.*': {'queue': 'default'},
    'leads.tasks.*': {'queue': 'default'},
    'live_classes.tasks.*': {'queue': 'default'},
    'analytics_reports.tasks.*': {'queue': 'default'},
}


CELERY_BEAT_SCHEDULE = {
    'dispatch-pending-email-jobs-every-minute': {
        'task': 'emails.tasks.dispatch_pending_email_jobs',
        'schedule': 60.0,
    },
    'process-pending-live-session-reminders-every-minute': {
        'task': 'live_classes.tasks.process_pending_live_session_reminders',
        'schedule': 60.0,
    },
    'update-live-session-statuses-every-minute': {
        'task': 'live_classes.tasks.update_live_session_statuses',
        'schedule': 60.0,
    },
    'cleanup-stuck-email-jobs-every-15-mins': {
        'task': 'emails.tasks.cleanup_stuck_processing_jobs',
        'schedule': 900.0,
    },
    'meter-due-storage-usage': {
        'task': 'storage.meter_due_storage_usage',
        'schedule': 10.0 if DEBUG else 60.0,
    },
    'debit-due-storage-billing-cycles': {
        'task': 'storage.debit_due_storage_billing_cycles',
        'schedule': 10.0 if DEBUG else 60.0,
    },
}






