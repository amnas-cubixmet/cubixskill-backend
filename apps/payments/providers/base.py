from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, Tuple, Optional
from payments.models import PaymentOrder, PaymentTransaction

class BasePaymentProvider(ABC):
    """
    Abstract interface for all payment providers (Stripe, Razorpay, PayPal, etc.).
    All gateway-specific interaction logic MUST be contained within sub-classes
    implementing this interface. Business logic outside the payment provider package
    must communicate only via this contract.
    """

    provider_name: str = "base"

    @abstractmethod
    def create_checkout_session(
        self,
        order: PaymentOrder,
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Creates a checkout or payment session with the provider gateway.
        Returns a normalized dict:
        {
            'gateway': str,
            'gateway_order_id': str,
            'checkout_url': str,
            'client_secret': str,
            'amount': str,
            'currency': str,
            'order_number': str,
            'raw': dict
        }
        """
        pass

    @abstractmethod
    def verify_payment(self, payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """
        Verifies payment authenticity and details.
        Returns a normalized dict:
        {
            'is_success': bool,
            'gateway_payment_id': str,
            'gateway_order_id': str,
            'amount': Decimal,
            'currency': str,
            'status': str,
            'payment_method': str,
            'raw': dict
        }
        """
        pass

    @abstractmethod
    def get_payment_status(self, gateway_payment_id_or_order_id: str) -> Dict[str, Any]:
        """
        Queries provider API to retrieve live payment status.
        Returns normalized status info dict.
        """
        pass

    @abstractmethod
    def refund_payment(
        self,
        transaction: PaymentTransaction,
        amount: Decimal,
        reason: str = "",
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Processes a full or partial refund via the provider API.
        Returns a normalized dict:
        {
            'gateway_refund_id': str,
            'status': str,
            'amount': Decimal,
            'raw': dict
        }
        """
        pass

    @abstractmethod
    def cancel_payment(self, gateway_order_id: str, reason: str = "") -> Dict[str, Any]:
        """
        Cancels an unpaid checkout session or order if supported by provider.
        Returns a normalized dict:
        {
            'status': str,
            'gateway_order_id': str,
            'raw': dict
        }
        """
        pass

    @abstractmethod
    def verify_webhook_signature(
        self,
        payload_body: Any,
        headers: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Verifies provider webhook cryptographic signature.
        Returns (is_valid, parsed_event_or_error_dict).
        """
        pass

    @abstractmethod
    def parse_webhook_event(
        self,
        payload_body: Any,
        headers: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Parses raw webhook body and headers into a normalized event dict:
        {
            'event_id': str,
            'event_type': str,
            'order_id': str,
            'gateway_order_id': str,
            'gateway_payment_id': str,
            'status': str,
            'amount': Decimal,
            'currency': str,
            'signature_valid': bool,
            'raw_payload': dict
        }
        """
        pass
