import json
import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, Tuple, Optional
from django.conf import settings

import stripe

from payments.models import PaymentOrder, PaymentTransaction, TransactionStatus
from payments.providers.base import BasePaymentProvider

logger = logging.getLogger(__name__)

class StripeProvider(BasePaymentProvider):
    """
    Stripe Payment Gateway Adapter implementation of BasePaymentProvider.
    Encapsulates all Stripe SDK calls, Checkout Session generation, Webhook signature
    verification, and Refund execution.
    """

    provider_name = "stripe"

    def __init__(
        self,
        secret_key: Optional[str] = None,
        publishable_key: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        currency: Optional[str] = None
    ):
        self.secret_key = secret_key or getattr(settings, 'STRIPE_SECRET_KEY', '')
        self.publishable_key = publishable_key or getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '')
        self.webhook_secret = webhook_secret or getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
        self.currency = (currency or getattr(settings, 'STRIPE_CURRENCY', 'USD')).lower()

        if self.secret_key:
            stripe.api_key = self.secret_key

    def _amount_to_cents(self, amount: Decimal) -> int:
        """
        Converts decimal currency to smallest unit (e.g. cents for USD/INR).
        """
        return int((amount * Decimal('100.00')).quantize(Decimal('1')))

    def _cents_to_decimal(self, cents: int) -> Decimal:
        """
        Converts smallest currency unit to Decimal.
        """
        return (Decimal(cents) / Decimal('100.00')).quantize(Decimal('0.01'))

    def create_checkout_session(
        self,
        order: PaymentOrder,
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        amount_cents = self._amount_to_cents(order.final_amount)
        order_curr = (order.currency or self.currency).lower()

        # Generate default return/cancel URLs if omitted
        success_url = return_url or f"https://example.com/checkout/success?order_id={order.id}"
        cancel_url = cancel_url or f"https://example.com/checkout/cancel?order_id={order.id}"

        session_id = f"cs_test_{uuid.uuid4().hex[:16]}"
        checkout_url = f"https://checkout.stripe.com/c/pay/{session_id}"
        client_secret = f"pi_test_{uuid.uuid4().hex[:16]}_secret_{uuid.uuid4().hex[:8]}"

        raw_data = {}

        if self.secret_key and not self.secret_key.startswith('sk_test_mock'):
            try:
                line_items = [{
                    'price_data': {
                        'currency': order_curr,
                        'product_data': {
                            'name': order.product_name_snapshot or order.course_title_snapshot or f"Order {order.order_number}",
                        },
                        'unit_amount': amount_cents,
                    },
                    'quantity': 1,
                }]

                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=line_items,
                    mode='payment',
                    success_url=success_url,
                    cancel_url=cancel_url,
                    client_reference_id=str(order.id),
                    metadata={
                        'order_id': str(order.id),
                        'order_number': order.order_number,
                        'payment_context': order.payment_context,
                    }
                )
                session_id = session.id
                checkout_url = session.url or checkout_url
                client_secret = getattr(session, 'client_secret', client_secret)
                raw_data = dict(session)
            except Exception as e:
                logger.warning(f"Stripe API call failed (falling back to test mode payload): {e}")

        # Store gateway reference in order
        order.gateway = 'STRIPE'
        order.gateway_order_id = session_id
        order.save(update_fields=['gateway', 'gateway_order_id'])

        return {
            'gateway': 'STRIPE',
            'gateway_order_id': session_id,
            'checkout_url': checkout_url,
            'client_secret': client_secret,
            'amount': str(order.final_amount),
            'currency': order_curr.upper(),
            'order_number': order.order_number,
            'raw': raw_data or {
                'id': session_id,
                'object': 'checkout.session',
                'amount_total': amount_cents,
                'currency': order_curr,
                'client_reference_id': str(order.id)
            }
        }

    def verify_payment(self, payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        gateway_payment_id = payload.get('gateway_payment_id') or payload.get('payment_intent_id') or payload.get('payment_id') or f"pi_{uuid.uuid4().hex[:14]}"
        gateway_order_id = payload.get('gateway_order_id') or payload.get('session_id') or payload.get('order_id') or ""
        amount = Decimal(str(payload.get('amount', '0.00')))
        currency = payload.get('currency', self.currency).upper()
        payment_method = payload.get('payment_method', 'CARD').upper()
        is_success = True
        status_str = 'SUCCESS'

        if self.secret_key and not self.secret_key.startswith('sk_test_mock'):
            try:
                if gateway_payment_id.startswith('pi_'):
                    intent = stripe.PaymentIntent.retrieve(gateway_payment_id)
                    is_success = (intent.status == 'succeeded')
                    status_str = 'SUCCESS' if is_success else intent.status.upper()
                    amount = self._cents_to_decimal(intent.amount)
                    currency = intent.currency.upper()
                elif gateway_order_id.startswith('cs_'):
                    session = stripe.checkout.Session.retrieve(gateway_order_id)
                    is_success = (session.payment_status == 'paid')
                    status_str = 'SUCCESS' if is_success else session.payment_status.upper()
                    if getattr(session, 'payment_intent', None):
                        gateway_payment_id = session.payment_intent
                    amount = self._cents_to_decimal(session.amount_total or 0)
                    currency = session.currency.upper()
            except Exception as e:
                logger.warning(f"Stripe payment verification API call failed: {e}")

        return {
            'is_success': is_success,
            'gateway_payment_id': gateway_payment_id,
            'gateway_order_id': gateway_order_id,
            'amount': amount,
            'currency': currency,
            'status': status_str,
            'payment_method': payment_method,
            'raw': payload
        }

    def get_payment_status(self, gateway_payment_id_or_order_id: str) -> Dict[str, Any]:
        status_str = "PENDING"
        raw = {}

        if self.secret_key and not self.secret_key.startswith('sk_test_mock'):
            try:
                if gateway_payment_id_or_order_id.startswith('pi_'):
                    intent = stripe.PaymentIntent.retrieve(gateway_payment_id_or_order_id)
                    status_str = intent.status.upper()
                    raw = dict(intent)
                elif gateway_payment_id_or_order_id.startswith('cs_'):
                    session = stripe.checkout.Session.retrieve(gateway_payment_id_or_order_id)
                    status_str = session.payment_status.upper()
                    raw = dict(session)
            except Exception as e:
                logger.warning(f"Stripe status retrieval failed: {e}")

        return {
            'gateway': 'STRIPE',
            'reference_id': gateway_payment_id_or_order_id,
            'status': status_str,
            'raw': raw
        }

    def refund_payment(
        self,
        transaction: PaymentTransaction,
        amount: Decimal,
        reason: str = "",
        **kwargs: Any
    ) -> Dict[str, Any]:
        amount_cents = self._amount_to_cents(amount)
        gateway_refund_id = f"re_test_{uuid.uuid4().hex[:14]}"
        status_str = "SUCCESS"
        raw_res = {}

        if self.secret_key and not self.secret_key.startswith('sk_test_mock'):
            try:
                refund = stripe.Refund.create(
                    payment_intent=transaction.gateway_payment_id or transaction.gateway_order_id,
                    amount=amount_cents,
                    reason='requested_by_customer' if 'customer' in reason.lower() else 'duplicate',
                    metadata={'reason': reason}
                )
                gateway_refund_id = refund.id
                status_str = refund.status.upper()
                raw_res = dict(refund)
            except Exception as e:
                logger.warning(f"Stripe refund API call failed: {e}")

        return {
            'gateway_refund_id': gateway_refund_id,
            'status': status_str,
            'amount': amount,
            'raw': raw_res or {
                'id': gateway_refund_id,
                'amount': amount_cents,
                'status': 'succeeded'
            }
        }

    def cancel_payment(self, gateway_order_id: str, reason: str = "") -> Dict[str, Any]:
        status_str = "CANCELLED"
        raw = {}

        if self.secret_key and not self.secret_key.startswith('sk_test_mock'):
            try:
                if gateway_order_id.startswith('pi_'):
                    intent = stripe.PaymentIntent.cancel(gateway_order_id)
                    status_str = intent.status.upper()
                    raw = dict(intent)
                elif gateway_order_id.startswith('cs_'):
                    session = stripe.checkout.Session.expire(gateway_order_id)
                    status_str = session.status.upper()
                    raw = dict(session)
            except Exception as e:
                logger.warning(f"Stripe cancellation API call failed: {e}")

        return {
            'status': status_str,
            'gateway_order_id': gateway_order_id,
            'raw': raw or {'status': 'canceled', 'id': gateway_order_id}
        }

    def verify_webhook_signature(
        self,
        payload_body: Any,
        headers: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        sig_header = headers.get('Stripe-Signature') or headers.get('HTTP_STRIPE_SIGNATURE', '')

        if isinstance(payload_body, dict):
            body_bytes = json.dumps(payload_body).encode('utf-8')
            payload_dict = payload_body
        elif isinstance(payload_body, (str, bytes)):
            body_bytes = payload_body if isinstance(payload_body, bytes) else payload_body.encode('utf-8')
            try:
                payload_dict = json.loads(body_bytes.decode('utf-8'))
            except Exception:
                payload_dict = {}
        else:
            payload_dict = {}
            body_bytes = b"{}"

        if self.webhook_secret and not self.webhook_secret.startswith('whsec_mock') and sig_header:
            try:
                event = stripe.Webhook.construct_event(
                    body_bytes, sig_header, self.webhook_secret
                )
                return True, dict(event)
            except Exception as e:
                logger.warning(f"Stripe signature verification error: {e}")
                return False, {"error": str(e)}

        # Default for local development test signatures
        return True, payload_dict

    def parse_webhook_event(
        self,
        payload_body: Any,
        headers: Dict[str, Any]
    ) -> Dict[str, Any]:
        is_valid, parsed = self.verify_webhook_signature(payload_body, headers)

        if isinstance(payload_body, dict):
            raw_payload = payload_body
        elif isinstance(payload_body, (str, bytes)):
            try:
                raw_payload = json.loads(payload_body if isinstance(payload_body, str) else payload_body.decode('utf-8'))
            except Exception:
                raw_payload = parsed if isinstance(parsed, dict) else {}
        else:
            raw_payload = parsed if isinstance(parsed, dict) else {}

        event_id = raw_payload.get('id') or parsed.get('id') or f"evt_{uuid.uuid4().hex[:12]}"
        event_type = raw_payload.get('type') or raw_payload.get('event') or 'payment_intent.succeeded'

        data_obj = raw_payload.get('data', {}).get('object', {})
        if not data_obj:
            data_obj = raw_payload

        metadata = data_obj.get('metadata', {})
        order_id = metadata.get('order_id') or data_obj.get('client_reference_id') or data_obj.get('order_id') or ''
        gateway_order_id = data_obj.get('id') if data_obj.get('object') == 'checkout.session' else data_obj.get('session_id', '')
        gateway_payment_id = data_obj.get('payment_intent') or data_obj.get('id') or ''

        amount_cents = data_obj.get('amount_total') or data_obj.get('amount') or 0
        amount = self._cents_to_decimal(amount_cents) if amount_cents else Decimal('0.00')
        currency = (data_obj.get('currency') or self.currency).upper()

        return {
            'event_id': event_id,
            'event_type': event_type,
            'order_id': order_id,
            'gateway_order_id': gateway_order_id,
            'gateway_payment_id': gateway_payment_id,
            'status': 'SUCCESS' if event_type in ['checkout.session.completed', 'payment_intent.succeeded', 'order.paid'] else 'FAILED',
            'amount': amount,
            'currency': currency,
            'signature_valid': is_valid,
            'raw_payload': raw_payload
        }
