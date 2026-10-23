import os
import sys
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers, default_methods
from dotenv import load_dotenv

from config.environment import env_bool, env_csv, env_int, env_origins

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

# Add apps directory to sys.path cleanly
APPS_DIR = BASE_DIR / 'apps'
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-cubixskill-production-backend-secret-key-change-in-prod')

DEBUG = env_bool('DEBUG', True)
# Captured at startup: Django's test runner later sets DEBUG=False even for
# tests of development-only short metering intervals.
STORAGE_ALLOW_10_SECOND_METERING = DEBUG

if not DEBUG and SECRET_KEY.startswith('django-insecure-'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("SECRET_KEY environment variable must be set to a secure secret when DEBUG is False.")

ALLOWED_HOSTS = env_csv(
    'ALLOWED_HOSTS',
    ('localhost', '127.0.0.1', '[::1]') if DEBUG else (),
)

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

# Database configuration: never silently change to SQLite when DATABASE_URL is supplied.
# Development defaults to SQLite. Use DATABASE_URL or USE_POSTGRES=true + DB_NAME for PostgreSQL.
if os.getenv('DATABASE_URL'):
    import dj_database_url

    DATABASES = {'default': dj_database_url.parse(os.environ['DATABASE_URL'])}
elif os.getenv('DB_NAME') and env_bool('USE_POSTGRES', False):
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
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {'timeout': 20},
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
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env_int('JWT_ACCESS_TOKEN_MINUTES', 60, minimum=1)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env_int('JWT_REFRESH_TOKEN_DAYS', 7, minimum=1)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Redis & Channels Configuration
REDIS_URL = os.getenv('REDIS_URL') or os.getenv('CELERY_BROKER_URL') or 'redis://127.0.0.1:6379/0'
USE_REDIS_CHANNELS = env_bool('USE_REDIS_CHANNELS', not DEBUG)

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
MINIO_USE_SSL = env_bool('MINIO_USE_SSL', False)

import mimetypes

mimetypes.add_type('application/vnd.apple.mpegurl', '.m3u8')
mimetypes.add_type('video/mp2t', '.ts')

MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'

IMAGE_MAX_SIZE_MB = 10
DOCUMENT_MAX_SIZE_MB = 25
VIDEO_MAX_SIZE_MB = 500
AUDIO_MAX_SIZE_MB = 100

LANGUAGE_CODE = os.getenv('LANGUAGE_CODE', 'en-us')
TIME_ZONE = os.getenv('TIME_ZONE', 'Asia/Kolkata')
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
EMAIL_PORT = env_int('EMAIL_PORT', 587, minimum=1)
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@cubixskill.com')

# FFmpeg & FFprobe Configuration
FFMPEG_BINARY = os.getenv('FFMPEG_BINARY', None)
FFPROBE_BINARY = os.getenv('FFPROBE_BINARY', None)

# Allowlist credentialed browser requests by exact origin. Local URLs are defaults
# only in DEBUG mode; production must declare its own origins in the environment.
# Both localhost and 127.0.0.1 are supported for public (5175), instructor (5173)
# and student (5174) development frontends.
LOCAL_BROWSER_ORIGINS = (
    'http://localhost:5173',
    'http://localhost:5174',
    'http://localhost:5175',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
    'http://127.0.0.1:5175',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env_origins(
    'CORS_ALLOWED_ORIGINS', LOCAL_BROWSER_ORIGINS if DEBUG else (),
)
CSRF_TRUSTED_ORIGINS = env_origins(
    'CSRF_TRUSTED_ORIGINS', LOCAL_BROWSER_ORIGINS if DEBUG else (),
)
CORS_ALLOW_HEADERS = list(default_headers) + ['x-portal']
CORS_ALLOW_METHODS = list(default_methods)

# Cookie Configuration for JWT Auth
AUTH_COOKIE_SECURE = env_bool('AUTH_COOKIE_SECURE', not DEBUG)
AUTH_COOKIE_SAMESITE = (os.getenv('AUTH_COOKIE_SAMESITE', 'Lax') or 'Lax').strip().capitalize()
AUTH_COOKIE_PATH = os.getenv('AUTH_COOKIE_PATH', '/') or '/'
AUTH_COOKIE_DOMAIN = os.getenv('AUTH_COOKIE_DOMAIN', '').strip() or None
if AUTH_COOKIE_SAMESITE not in ('Lax', 'Strict', 'None'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('AUTH_COOKIE_SAMESITE must be Lax, Strict, or None.')
if AUTH_COOKIE_SAMESITE == 'None' and not AUTH_COOKIE_SECURE:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('AUTH_COOKIE_SAMESITE=None requires AUTH_COOKIE_SECURE=True and HTTPS.')

# HTTPS Security Header Configuration
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', True)
    CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', True)
    SECURE_HSTS_SECONDS = env_int('SECURE_HSTS_SECONDS', 31536000, minimum=0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', True)
    SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    if env_bool('USE_SECURE_PROXY_HEADER', False):
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
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL') or REDIS_URL
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND') or REDIS_URL

CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env_int('CELERY_TASK_TIME_LIMIT_SECONDS', 30 * 60, minimum=60)
CELERY_WORKER_PREFETCH_MULTIPLIER = env_int('CELERY_WORKER_PREFETCH_MULTIPLIER', 1, minimum=1)

CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = env_int('CELERY_BROKER_CONNECTION_MAX_RETRIES', 3, minimum=1)
CELERY_RESULT_BACKEND_MAX_RETRIES = env_int('CELERY_RESULT_BACKEND_MAX_RETRIES', 3, minimum=1)
CELERY_RESULT_EXPIRES = env_int('CELERY_RESULT_EXPIRES_SECONDS', 86400, minimum=60)

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


# Do not run 10-second storage billing metering in production.
STORAGE_BILLING_BEAT_INTERVAL = env_int(
    'STORAGE_BILLING_BEAT_INTERVAL_SECONDS',
    10 if DEBUG else 60,
    minimum=1 if DEBUG else 60,
)

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
        'schedule': float(STORAGE_BILLING_BEAT_INTERVAL),
    },
    'debit-due-storage-billing-cycles': {
        'task': 'storage.debit_due_storage_billing_cycles',
        'schedule': float(STORAGE_BILLING_BEAT_INTERVAL),
    },
}






