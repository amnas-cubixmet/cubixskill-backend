import logging
from typing import Dict, Type, Optional
from django.conf import settings

from payments.providers.base import BasePaymentProvider
from payments.providers.razorpay_provider import RazorpayProvider

logger = logging.getLogger(__name__)


class PaymentProviderFactory:
    """
    Registry & Factory for instantiating gateway-agnostic payment providers.
    Currently defaults to Razorpay as the official payment gateway for CubixSkill.
    """

    _providers: Dict[str, Type[BasePaymentProvider]] = {}

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[BasePaymentProvider]) -> None:
        """
        Registers a payment provider class under a name (e.g. 'razorpay').
        """
        cls._providers[name.lower()] = provider_class
        logger.info(f"Registered payment provider: '{name.lower()}' ({provider_class.__name__})")

    @classmethod
    def get_provider(cls, gateway_name: Optional[str] = None) -> BasePaymentProvider:
        """
        Returns an initialized instance of the requested payment provider.
        Defaults to Razorpay if gateway_name is omitted or unavailable.
        """
        provider_key = (gateway_name or getattr(settings, 'PAYMENT_PROVIDER', 'razorpay')).lower()

        if provider_key not in cls._providers:
            # Fallback to Razorpay
            logger.info(f"Using default 'razorpay' provider.")
            provider_key = 'razorpay'
            if 'razorpay' not in cls._providers:
                cls.register_provider('razorpay', RazorpayProvider)

        provider_cls = cls._providers[provider_key]
        return provider_cls()


# Pre-register official Razorpay provider
PaymentProviderFactory.register_provider('razorpay', RazorpayProvider)
