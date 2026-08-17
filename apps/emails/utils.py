import os
from django.conf import settings

def get_frontend_url() -> str:
    return getattr(settings, 'FRONTEND_ACADEMY_URL', os.getenv('FRONTEND_ACADEMY_URL', 'http://localhost:5173')).rstrip('/')

def build_setup_password_url(raw_token: str) -> str:
    base_url = get_frontend_url()
    return f"{base_url}/setup-password?token={raw_token}"

def build_reset_password_url(raw_token: str, academy_slug: str = None) -> str:
    base_url = get_frontend_url()
    return f"{base_url}/reset-password?token={raw_token}"

def build_verify_email_url(raw_token: str, academy_slug: str = None) -> str:
    base_url = get_frontend_url()
    return f"{base_url}/verify-email?token={raw_token}"
