import logging
from typing import Dict, Type, Optional
from django.conf import settings

from payments.providers.base import BasePaymentProvider
from payments.providers.stripe_provider import StripeProvider

logger = logging.getLogger(__name__)

class PaymentProviderFactory:
    """
    Registry & Factory for instantiating gateway-agnostic payment providers.
    Allows changing gateways seamlessly via configuration or selecting specific
    provider instances for multi-gateway support.
    """

    _providers: Dict[str, Type[BasePaymentProvider]] = {}

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[BasePaymentProvider]) -> None:
        """
        Registers a payment provider class under a name (e.g. 'stripe', 'razorpay', 'paypal').
        """
        cls._providers[name.lower()] = provider_class
        logger.info(f"Registered payment provider: '{name.lower()}' ({provider_class.__name__})")

    @classmethod
    def get_provider(cls, gateway_name: Optional[str] = None) -> BasePaymentProvider:
        """
        Returns an initialized instance of the requested payment provider.
        If gateway_name is omitted or None, falls back to settings.PAYMENT_PROVIDER ('stripe').
        """
        provider_key = (gateway_name or getattr(settings, 'PAYMENT_PROVIDER', 'stripe')).lower()

        if provider_key not in cls._providers:
            # Fallback auto-registration for core providers
            if provider_key == 'stripe':
                cls.register_provider('stripe', StripeProvider)
            else:
                # Fallback to Stripe if unknown provider is passed
                logger.warning(f"Payment provider '{provider_key}' not registered. Falling back to 'stripe'.")
                provider_key = 'stripe'
                if 'stripe' not in cls._providers:
                    cls.register_provider('stripe', StripeProvider)

        provider_cls = cls._providers[provider_key]
        return provider_cls()


# Pre-register built-in Stripe provider
PaymentProviderFactory.register_provider('stripe', StripeProvider)
