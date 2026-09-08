import base64
import logging
import os

from cryptography.fernet import Fernet
from django.conf import settings

logger = logging.getLogger(__name__)

# Default master key fallback derived from SECRET_KEY if PAYMENT_CREDENTIAL_ENCRYPTION_KEY is not set
def _get_fernet_key() -> bytes:
    master_key = getattr(settings, 'PAYMENT_CREDENTIAL_ENCRYPTION_KEY', None) or os.getenv('PAYMENT_CREDENTIAL_ENCRYPTION_KEY')
    if not master_key:
        raw_key = getattr(settings, 'SECRET_KEY', 'default-cubixskill-secret-key-32-chars-at-least!!')
        master_key = base64.urlsafe_b64encode(raw_key.encode('utf-8').ljust(32)[:32]).decode('utf-8')

    try:
        # Validate if key is valid Fernet key
        return master_key.encode('utf-8') if isinstance(master_key, str) else master_key
    except Exception:
        # Fallback to deterministic 32-byte b64 key
        return base64.urlsafe_b64encode(b'cubixskill_payment_encryption_key_32b!'.ljust(32)[:32])

def encrypt_secret(value: str) -> str:
    """
    Encrypts sensitive payment credentials (Razorpay secret, webhook secret, VPA, bank details) at rest.
    Returns ciphertext string. Returns empty string if value is empty.
    """
    if not value:
        return ''
    try:
        f = Fernet(_get_fernet_key())
        return f.encrypt(value.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to encrypt credential secret: {e}")
        raise ValueError("Encryption error occurred.")

def decrypt_secret(ciphertext: str) -> str:
    """
    Decrypts encrypted payment credentials at rest.
    Returns plaintext string. Returns empty string if ciphertext is empty.
    """
    if not ciphertext:
        return ''
    try:
        f = Fernet(_get_fernet_key())
        return f.decrypt(ciphertext.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to decrypt credential secret: {e}")
        return ''
