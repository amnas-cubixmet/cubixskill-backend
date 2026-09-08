import logging

import razorpay
from django.conf import settings
from payments.encryption_service import decrypt_secret

logger = logging.getLogger(__name__)

class PaymentMode:
    ACADEMY_RAZORPAY = "ACADEMY_RAZORPAY"
    CUBIXSKILL_RAZORPAY = "CUBIXSKILL_RAZORPAY"

def resolve_payment_credentials(academy) -> dict:
    """
    Resolves Razorpay credentials and SDK client dynamically for an Academy based on its Payment Mode.
    
    Mode 1: ACADEMY_RAZORPAY -> Decrypts and uses Academy's own connected Razorpay account.
    Mode 2: CUBIXSKILL_RAZORPAY -> Uses CubixSkill central Razorpay account from environment settings.
    
    Returns dict containing:
      - payment_mode
      - key_id
      - key_secret
      - webhook_secret
      - environment ('test' | 'live')
      - razorpay_client (instance of razorpay.Client)
    """
    from payments.models import AcademyPaymentSettings
    from payments.models import PaymentMode as ModelPaymentMode

    payment_settings = None
    if academy:
        try:
            payment_settings = getattr(academy, 'payment_settings', None) or AcademyPaymentSettings.objects.filter(academy=academy).first()
        except Exception as e:
            logger.warning(f"Could not fetch payment settings for academy {getattr(academy, 'uuid', academy)}: {e}")

    # Mode 1: Academy Own Razorpay Account
    if payment_settings and payment_settings.payment_mode == ModelPaymentMode.ACADEMY_RAZORPAY:
        key_id = payment_settings.razorpay_key_id
        key_secret = decrypt_secret(payment_settings.razorpay_key_secret_encrypted)
        webhook_secret = decrypt_secret(payment_settings.razorpay_webhook_secret_encrypted)

        if key_id and key_secret:
            client = razorpay.Client(auth=(key_id, key_secret))
            return {
                "payment_mode": ModelPaymentMode.ACADEMY_RAZORPAY,
                "key_id": key_id,
                "key_secret": key_secret,
                "webhook_secret": webhook_secret,
                "environment": payment_settings.razorpay_environment or 'test',
                "razorpay_client": client,
                "settings": payment_settings,
            }

    # Mode 2: CubixSkill Central Payment Account (Default Fallback)
    central_key_id = getattr(settings, 'RAZORPAY_KEY_ID', '') or 'rzp_test_cubixskill_central'
    central_key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '') or 'mock_central_secret_123456'
    central_webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '') or 'mock_central_webhook_secret'

    client = razorpay.Client(auth=(central_key_id, central_key_secret))
    return {
        "payment_mode": ModelPaymentMode.CUBIXSKILL_RAZORPAY,
        "key_id": central_key_id,
        "key_secret": central_key_secret,
        "webhook_secret": central_webhook_secret,
        "environment": "live" if getattr(settings, 'PAYMENT_LIVE_MODE', False) else "test",
        "razorpay_client": client,
        "settings": payment_settings,
    }
