import os

from django.conf import settings


def get_instructor_frontend_url() -> str:
    return getattr(settings, 'FRONTEND_ACADEMY_URL', os.getenv('FRONTEND_ACADEMY_URL', 'http://localhost:5173')).rstrip('/')

def get_student_frontend_url() -> str:
    return getattr(settings, 'STUDENT_PUBLIC_URL', getattr(settings, 'STUDENT_FRONTEND_URL', os.getenv('STUDENT_PUBLIC_URL', 'http://localhost:5174'))).rstrip('/')

def get_frontend_url(portal: str = 'instructor') -> str:
    if portal == 'student':
        return get_student_frontend_url()
    return get_instructor_frontend_url()

def build_setup_password_url(raw_token: str, academy_uuid: str = None, portal: str = 'instructor') -> str:
    base_url = get_frontend_url(portal)
    if academy_uuid:
        return f"{base_url}/{academy_uuid}/setup-password?token={raw_token}"
    return f"{base_url}/setup-password?token={raw_token}"

def build_reset_password_url(raw_token: str, academy_uuid: str = None, portal: str = 'instructor') -> str:
    base_url = get_frontend_url(portal)
    if academy_uuid:
        return f"{base_url}/{academy_uuid}/reset-password?token={raw_token}"
    return f"{base_url}/reset-password?token={raw_token}"

def build_verify_email_url(raw_token: str, academy_uuid: str = None, portal: str = 'instructor') -> str:
    base_url = get_frontend_url(portal)
    if academy_uuid:
        return f"{base_url}/{academy_uuid}/verify-email?token={raw_token}"
    return f"{base_url}/verify-email?token={raw_token}"

