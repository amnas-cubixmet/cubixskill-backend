import logging
from typing import Dict, Any, Optional
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

from emails.constants import EmailTemplateCodes, SUBJECTS
from emails.utils import (
    build_setup_password_url,
    build_reset_password_url,
    build_verify_email_url
)

logger = logging.getLogger(__name__)

def send_transactional_email(
    recipient: str,
    template_name: str,
    subject: str,
    context: Dict[str, Any],
    from_email: Optional[str] = None
) -> bool:
    """
    Renders HTML and plain-text templates and sends a transactional email using
    Django's configured email backend. Logs success/failure safely without revealing tokens or passwords.
    """
    if not recipient:
        logger.error("Failed to send transactional email: missing recipient.")
        return False

    sender = from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cubixskill.com')
    html_template = f"emails/{template_name}.html"
    text_template = f"emails/{template_name}.txt"

    try:
        html_content = render_to_string(html_template, context)
        text_content = render_to_string(text_template, context)
    except Exception as e:
        logger.error(f"Template rendering error for template '{template_name}': {str(e)}")
        # Fallback to context body if rendering fails
        html_content = f"<p>{context.get('body', subject)}</p>"
        text_content = context.get('body', subject)

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=sender,
            to=[recipient]
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        logger.info(f"Transactional email '{subject}' sent successfully to {recipient}")
        return True
    except Exception as e:
        logger.error(f"SMTP/Email delivery failure to {recipient} for subject '{subject}': {str(e)}")
        return False


def send_academy_activation_email(user, academy, raw_token: str) -> bool:
    """
    Sends Academy Activation & Setup Password email to the Academy Administrator.
    """
    action_url = build_setup_password_url(raw_token)
    subject = SUBJECTS[EmailTemplateCodes.ACADEMY_ACCOUNT_SETUP]
    context = {
        "user_name": user.full_name or "Administrator",
        "academy_name": academy.name if academy else "Your Academy",
        "action_url": action_url,
        "recipient_email": user.email,
    }
    return send_transactional_email(
        recipient=user.email,
        template_name="academy_activation",
        subject=subject,
        context=context
    )


def send_password_reset_email(user, raw_token: str) -> bool:
    """
    Sends Password Reset link email.
    """
    academy_slug = user.academy.slug if user.academy else None
    action_url = build_reset_password_url(raw_token, academy_slug=academy_slug)
    subject = SUBJECTS[EmailTemplateCodes.PASSWORD_RESET]
    context = {
        "user_name": user.full_name or "User",
        "action_url": action_url,
        "recipient_email": user.email,
    }
    return send_transactional_email(
        recipient=user.email,
        template_name="password_reset",
        subject=subject,
        context=context
    )


def send_password_changed_email(user) -> bool:
    """
    Sends Password Change Confirmation security alert email.
    """
    subject = SUBJECTS[EmailTemplateCodes.PASSWORD_CHANGED]
    context = {
        "user_name": user.full_name or "User",
        "recipient_email": user.email,
        "timestamp": timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    return send_transactional_email(
        recipient=user.email,
        template_name="password_changed",
        subject=subject,
        context=context
    )


def send_verification_email(user, raw_token: str) -> bool:
    """
    Sends Email Verification link email.
    """
    academy_slug = user.academy.slug if user.academy else None
    action_url = build_verify_email_url(raw_token, academy_slug=academy_slug)
    subject = SUBJECTS[EmailTemplateCodes.EMAIL_VERIFICATION]
    context = {
        "user_name": user.full_name or "User",
        "action_url": action_url,
        "recipient_email": user.email,
    }
    return send_transactional_email(
        recipient=user.email,
        template_name="verification",
        subject=subject,
        context=context
    )


def send_student_activation_email(user, academy, raw_token: str, expiry_time: str = "24 hours") -> bool:
    """
    Sends Student Account Activation email.
    """
    action_url = build_setup_password_url(raw_token)
    academy_name = academy.name if academy else "CubixSkill Academy"
    subject = f"Activate Your Student Account – {academy_name}"
    support_email = getattr(academy, 'support_email', None) or getattr(settings, 'SUPPORT_EMAIL', 'support@cubixskill.com')
    context = {
        "student_name": user.full_name or "Student",
        "student_email": user.email,
        "academy_name": academy_name,
        "activation_url": action_url,
        "expiry_time": expiry_time,
        "academy_support_email": support_email,
    }
    return send_transactional_email(
        recipient=user.email,
        template_name="student_activation",
        subject=subject,
        context=context
    )

