import logging
from typing import Dict, Any, Optional
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from emails.utils import build_reset_password_url, build_verify_email_url, build_setup_password_url

logger = logging.getLogger(__name__)

class EmailTemplateCodes:
    ACADEMY_ACTIVATION = "academy_activation"
    PASSWORD_RESET = "password_reset"
    PASSWORD_CHANGED = "password_changed"
    EMAIL_VERIFICATION = "email_verification"

SUBJECTS = {
    EmailTemplateCodes.ACADEMY_ACTIVATION: "Activate Your CubixSkill Academy Account",
    EmailTemplateCodes.PASSWORD_RESET: "Reset Your CubixSkill Password",
    EmailTemplateCodes.PASSWORD_CHANGED: "Your CubixSkill Password Has Been Changed",
    EmailTemplateCodes.EMAIL_VERIFICATION: "Verify Your Email Address – CubixSkill",
}

def send_transactional_email(
    recipient: str,
    template_name: str,
    subject: str,
    context: Dict[str, Any]
) -> bool:
    """
    Sends transactional HTML + Plain text email via Django's SMTP backend.
    """
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cubixskill.com')
        html_content = render_to_string(f"emails/{template_name}.html", context)
        text_content = strip_tags(html_content)

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[recipient]
        )
        email.attach_alternative(html_content, "text/html")
        email.send(fail_silently=False)
        logger.info(f"Transactional email '{template_name}' sent successfully to {recipient}")
        return True
    except Exception as e:
        logger.error(f"Failed to send transactional email '{template_name}' to {recipient}: {str(e)}", exc_info=True)
        return False


def send_academy_activation_email(user, academy, raw_token: str, expiry_time: str = "24 hours") -> bool:
    """
    Sends Academy Activation / Initial Admin Password Setup email.
    """
    academy_uuid = str(academy.pk) if academy else None
    action_url = build_setup_password_url(raw_token, academy_uuid=academy_uuid)
    subject = SUBJECTS[EmailTemplateCodes.ACADEMY_ACTIVATION]
    context = {
        "user_name": user.full_name or "Academy Admin",
        "academy_name": academy.name if academy else "Your Academy",
        "action_url": action_url,
        "expiry_time": expiry_time,
        "recipient_email": user.email,
    }
    return send_transactional_email(
        recipient=user.email,
        template_name="academy_activation",
        subject=subject,
        context=context
    )


def send_password_reset_email(user, raw_token: str, expiry_time: str = "1 hour") -> bool:
    """
    Sends Password Reset link email.
    """
    target_academy = getattr(user, 'academy', None)
    academy_uuid = str(target_academy.pk) if target_academy else None
    action_url = build_reset_password_url(raw_token, academy_uuid=academy_uuid)
    subject = SUBJECTS[EmailTemplateCodes.PASSWORD_RESET]
    context = {
        "user_name": user.full_name or "User",
        "action_url": action_url,
        "expiry_time": expiry_time,
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
    Sends Password Changed Confirmation email.
    """
    subject = SUBJECTS[EmailTemplateCodes.PASSWORD_CHANGED]
    context = {
        "user_name": user.full_name or "User",
        "recipient_email": user.email,
    }
    return send_transactional_email(
        recipient=user.email,
        template_name="password_changed",
        subject=subject,
        context=context
    )


def send_verification_email(user, raw_token: str, academy=None) -> bool:
    """
    Sends Email Verification link email.
    """
    target_academy = academy or getattr(user, 'academy', None)
    academy_uuid = str(target_academy.pk) if target_academy else None
    action_url = build_verify_email_url(raw_token, academy_uuid=academy_uuid)
    academy_name = target_academy.name if target_academy else "CubixSkill Academy"
    subject = f"Verify Your Email – {academy_name}"
    context = {
        "user_name": user.full_name or "User",
        "action_url": action_url,
        "recipient_email": user.email,
        "academy_name": academy_name,
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
    academy_uuid = str(academy.pk) if academy else None
    action_url = build_setup_password_url(raw_token, academy_uuid=academy_uuid)
    academy_name = academy.name if academy else "CubixSkill Academy"
    subject = f"Set up your CubixSkill student password – {academy_name}"
    context = {
        "user_name": user.full_name or "Student",
        "academy_name": academy_name,
        "action_url": action_url,
        "expiry_time": expiry_time,
        "recipient_email": user.email,
    }
    return send_transactional_email(
        recipient=user.email,
        template_name="student_activation",
        subject=subject,
        context=context
    )
