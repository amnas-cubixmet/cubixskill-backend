import hashlib
import secrets
from datetime import timedelta

from core.models import BaseModel
from django.db import models
from django.utils import timezone
from users_roles.models import User

#--------------------------------------------------------------
# TokenType
#--------------------------------------------------------------

class TokenType(models.TextChoices):
    EMAIL_VERIFICATION = 'EMAIL_VERIFICATION', 'Email Verification'
    PASSWORD_SETUP = 'PASSWORD_SETUP', 'Password Setup'
    PASSWORD_RESET = 'PASSWORD_RESET', 'Password Reset'

#--------------------------------------------------------------
# AuthToken
#--------------------------------------------------------------

class AuthToken(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auth_tokens', null=True, blank=True)
    token_type = models.CharField(max_length=30, choices=TokenType.choices, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'auth_tokens'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.token_type}"

    @property
    def is_valid(self) -> bool:
        now = timezone.now()
        return self.used_at is None and self.revoked_at is None and self.expires_at > now

#--------------------------------------------------------------
# Token Service
#--------------------------------------------------------------

class AuthTokenService:
    @staticmethod
    def _hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    @classmethod
    def generate_token(cls, user: User, token_type: str, expiry_hours: int = 24) -> str:
        # Revoke active previous tokens of the same type for this user
        cls.revoke_existing_tokens(user, token_type)

        raw_token = secrets.token_urlsafe(32)
        token_hash = cls._hash_token(raw_token)
        expires_at = timezone.now() + timedelta(hours=expiry_hours)

        AuthToken.objects.create(
            user=user,
            token_type=token_type,
            token_hash=token_hash,
            expires_at=expires_at
        )

        return raw_token

    @classmethod
    def validate_token_peek(cls, raw_token: str, expected_types=None) -> User:
        token_hash = cls._hash_token(raw_token)
        query = AuthToken.objects.filter(
            token_hash=token_hash,
            used_at__isnull=True,
            revoked_at__isnull=True
        ).select_related('user')
        if expected_types:
            if isinstance(expected_types, list):
                query = query.filter(token_type__in=expected_types)
            else:
                query = query.filter(token_type=expected_types)

        auth_token = query.first()
        if not auth_token or not auth_token.is_valid:
            return None
        return auth_token.user

    @classmethod
    def validate_and_consume(cls, raw_token: str, expected_type: str) -> User:
        token_hash = cls._hash_token(raw_token)
        auth_token = AuthToken.objects.filter(
            token_hash=token_hash,
            token_type=expected_type,
            used_at__isnull=True,
            revoked_at__isnull=True
        ).select_related('user').first()

        if not auth_token or not auth_token.is_valid:
            return None

        # Atomic mark as used
        auth_token.used_at = timezone.now()
        auth_token.save(update_fields=['used_at'])
        return auth_token.user


    @classmethod
    def validate_reset_token(cls, raw_token: str):
        """
        Validates token status specifically for reset password without consuming it yet.
        Returns: (auth_token, user, error_message, error_code)
        """
        if not raw_token:
            return None, None, "Reset token is required.", "TOKEN_REQUIRED"

        token_hash = cls._hash_token(raw_token)
        auth_token = AuthToken.objects.filter(
            token_hash=token_hash,
            token_type=TokenType.PASSWORD_RESET
        ).select_related('user').first()

        if not auth_token:
            return None, None, "Invalid reset token.", "TOKEN_INVALID"

        if auth_token.used_at is not None:
            return None, None, "This reset token has already been used.", "TOKEN_ALREADY_USED"

        if auth_token.revoked_at is not None:
            return None, None, "This reset token has been revoked.", "TOKEN_REVOKED"

        if auth_token.expires_at <= timezone.now():
            return None, None, "This reset token has expired.", "TOKEN_EXPIRED"

        return auth_token, auth_token.user, None, None

    @classmethod
    def mark_token_used(cls, auth_token: AuthToken):
        auth_token.used_at = timezone.now()
        auth_token.save(update_fields=['used_at'])

    @classmethod
    def revoke_existing_tokens(cls, user: User, token_type: str):
        AuthToken.objects.filter(
            user=user,
            token_type=token_type,
            used_at__isnull=True,
            revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
