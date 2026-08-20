import os
import sys
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# Add apps directory to sys.path cleanly
APPS_DIR = BASE_DIR / 'apps'
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-cubixskill-production-backend-secret-key-change-in-prod')

DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 't')

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')

AUTH_USER_MODEL = 'users_roles.User'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
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
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
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

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

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

MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'

IMAGE_MAX_SIZE_MB = 10
DOCUMENT_MAX_SIZE_MB = 25
VIDEO_MAX_SIZE_MB = 500
AUDIO_MAX_SIZE_MB = 100

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Payment Gateway Configuration (Provider-Agnostic)
PAYMENT_PROVIDER = os.getenv('PAYMENT_PROVIDER', 'stripe').lower()
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
STRIPE_CURRENCY = os.getenv('STRIPE_CURRENCY', 'USD')

# Email Configuration (Supports SMTP App Password via EMAIL_HOST_PASSWORD)
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend' if not DEBUG else 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@cubixskill.com')

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# Frontend URL Configuration
FRONTEND_ACADEMY_URL = os.getenv('FRONTEND_ACADEMY_URL', 'http://localhost:5173')

# Authentication Settings
LOGIN_URL = '/control/login/'
LOGIN_REDIRECT_URL = '/control/dashboard/'




