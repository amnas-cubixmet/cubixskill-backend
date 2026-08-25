import uuid
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from courses.models import Course
from users_roles.models import User
from enrollments.services import EnrollmentService
from credits.services import CreditsService
from notifications.services import EmailService
from payments.models import (
    PaymentOrder,
    PaymentTransaction,
    Coupon,
    CouponRedemption,
    PaymentRefund,
    PaymentInvoice,
    PaymentWebhookEvent,
    PaymentContext,
    OrderStatus,
    TransactionStatus,
    CouponScope,
    DiscountType,
    GatewayType,
    PaymentMethod,
    RefundStatus,
)

from payments.providers.factory import PaymentProviderFactory
from payments.providers.base import BasePaymentProvider

# --------------------------------------------------------------
# 1. Payment Gateway Abstraction Service
# Central facade for provider-agnostic payment execution.
# Communicates exclusively with BasePaymentProvider implementations
# obtained via PaymentProviderFactory.
# --------------------------------------------------------------

class PaymentGatewayService:

    @classmethod
    def get_provider(cls, gateway: str = None) -> BasePaymentProvider:
        """
        Retrieves the provider adapter for the specified gateway name.
        """
        return PaymentProviderFactory.get_provider(gateway)

    @classmethod
    def create_gateway_order(cls, order: PaymentOrder, return_url: str = None, cancel_url: str = None) -> dict:
        """
        Creates checkout/payment session reference using active payment provider.
        """
        from core.utils import normalize_currency
        order.currency = normalize_currency(order.currency)
        provider = cls.get_provider(order.gateway)
        session_data = provider.create_checkout_session(
            order=order,
            return_url=return_url,
            cancel_url=cancel_url
        )
        return session_data

    @classmethod
    def verify_payment(cls, gateway: str, payload: dict) -> dict:
        """
        Verifies transaction authenticity via provider adapter.
        """
        provider = cls.get_provider(gateway)
        return provider.verify_payment(payload)

    @classmethod
    def verify_webhook_signature(cls, gateway: str, payload_body: any, headers: dict = None) -> tuple[bool, dict]:
        """
        Verifies provider signature for incoming webhooks.
        """
        provider = cls.get_provider(gateway)
        return provider.verify_webhook_signature(payload_body, headers or {})

    @classmethod
    def process_gateway_refund(cls, transaction_obj: PaymentTransaction, amount: Decimal, reason: str = "") -> dict:
        """
        Executes refund via active gateway provider.
        """
        provider = cls.get_provider(transaction_obj.gateway)
        return provider.refund_payment(transaction_obj, amount=amount, reason=reason)

    @classmethod
    def cancel_payment(cls, gateway: str, gateway_order_id: str, reason: str = "") -> dict:
        """
        Cancels unpaid session/order where supported.
        """
        provider = cls.get_provider(gateway)
        return provider.cancel_payment(gateway_order_id=gateway_order_id, reason=reason)

# --------------------------------------------------------------
# 2. Coupon Service
# Validates coupon eligibility and calculates trusted discount values.
# The backend calculates the final discount; client-submitted discount
# totals are never trusted.
# --------------------------------------------------------------

class CouponService:

    @classmethod
    def validate_coupon(
        cls,
        code: str,
        user: User,
        payment_context: str,
        academy: Academy = None,
        course: Course = None,
        order_amount: Decimal = Decimal('0.00')
    ) -> Coupon:
        """
        Validates coupon code against scope, academy, course target, validity dates, and usage limits.
        """
        now = timezone.now()
        coupon = Coupon.objects.filter(code__iexact=code.strip(), is_active=True).first()
        if not coupon:
            raise ValidationError({"coupon_code": "Invalid or inactive coupon code."})

        # 1. Scope & Context Validation
        if payment_context == PaymentContext.COURSE_PURCHASE:
            if coupon.scope != CouponScope.ACADEMY_COURSE:
                raise ValidationError({"coupon_code": "Platform coupons cannot be applied to Course checkouts."})
            if coupon.academy and coupon.academy != academy:
                raise ValidationError({"coupon_code": "Coupon is not valid for this Academy."})
            if coupon.courses.exists() and course:
                if not coupon.courses.filter(id=course.id).exists():
                    raise ValidationError({"coupon_code": "Coupon is not valid for the selected Course."})

        elif payment_context == PaymentContext.PLATFORM_PURCHASE:
            if coupon.scope != CouponScope.PLATFORM:
                raise ValidationError({"coupon_code": "Course coupons cannot be applied to platform purchases."})

        # 2. Validity Window
        if coupon.valid_from and now < coupon.valid_from:
            raise ValidationError({"coupon_code": "Coupon is not yet active."})
        if coupon.valid_until and now > coupon.valid_until:
            raise ValidationError({"coupon_code": "Coupon has expired."})

        # 3. Minimum Order Amount
        if order_amount < coupon.minimum_order_amount:
            raise ValidationError({"coupon_code": f"Minimum order amount for this coupon is {coupon.minimum_order_amount}."})

        # 4. Total Usage Limit
        if coupon.total_usage_limit > 0 and coupon.current_usage_count >= coupon.total_usage_limit:
            raise ValidationError({"coupon_code": "Coupon total usage limit reached."})

        # 5. Per User Usage Limit
        if user and user.is_authenticated:
            user_redemptions = CouponRedemption.objects.filter(coupon=coupon, user=user).count()
            if user_redemptions >= coupon.per_user_usage_limit:
                raise ValidationError({"coupon_code": "You have already reached the maximum usage limit for this coupon."})

        # 6. First Purchase Only
        if coupon.first_purchase_only and user and user.is_authenticated:
            previous_orders = PaymentOrder.objects.filter(payer=user, status=OrderStatus.COMPLETED).exists()
            if previous_orders:
                raise ValidationError({"coupon_code": "Coupon is only valid for first-time purchases."})

        return coupon

    @classmethod
    def calculate_discount(cls, coupon: Coupon, order_amount: Decimal) -> Decimal:
        """
        Calculates authoritative discount amount based on percentage or fixed value.
        """
        if coupon.discount_type == DiscountType.PERCENTAGE:
            discount = (order_amount * coupon.discount_value) / Decimal('100.00')
            if coupon.max_discount_amount and discount > coupon.max_discount_amount:
                discount = coupon.max_discount_amount
        else:
            discount = min(coupon.discount_value, order_amount)

        return discount.quantize(Decimal('0.01'))

# --------------------------------------------------------------
# 3. Payment Pricing Service
# Recalculates subtotal, discount, tax, and final amount on the backend.
# Never trust monetary totals supplied by the frontend.
# --------------------------------------------------------------

class PaymentPricingService:

    @classmethod
    def calculate_order_pricing(
        cls,
        subtotal_amount: Decimal = None,
        coupon_code: str = None,
        user: User = None,
        payment_context: str = PaymentContext.COURSE_PURCHASE,
        academy: Academy = None,
        course: Course = None
    ) -> dict:
        from courses.services import CoursePricingService

        if course and payment_context == PaymentContext.COURSE_PURCHASE:
            regular_price = Decimal(str(course.price)).quantize(Decimal('0.01')) if course.price is not None else Decimal('0.00')
            effective_price = CoursePricingService.get_course_effective_price(course).quantize(Decimal('0.01'))
            sale_discount = max(Decimal('0.00'), regular_price - effective_price)
            subtotal = effective_price
        else:
            effective_price = Decimal(str(subtotal_amount or '0.00')).quantize(Decimal('0.01'))
            regular_price = effective_price
            sale_discount = Decimal('0.00')
            subtotal = effective_price

        coupon_discount = Decimal('0.00')
        coupon = None

        if coupon_code:
            coupon = CouponService.validate_coupon(
                code=coupon_code,
                user=user,
                payment_context=payment_context,
                academy=academy,
                course=course,
                order_amount=subtotal
            )
            coupon_discount = CouponService.calculate_discount(coupon, subtotal)

        total_discount = sale_discount + coupon_discount
        taxable_amount = max(Decimal('0.00'), subtotal - coupon_discount)
        tax = Decimal('0.00')  # Configurable tax engine hook
        final_amount = taxable_amount + tax

        return {
            'regular_price': regular_price,
            'sale_price': effective_price if sale_discount > Decimal('0.00') else None,
            'sale_discount': sale_discount,
            'coupon_discount': coupon_discount,
            'subtotal': subtotal,
            'discount': total_discount,
            'tax': tax,
            'tax_amount': tax,
            'final_amount': final_amount,
            'coupon': coupon,
        }

# --------------------------------------------------------------
# 4. Payment Order Service
# Creates business payment orders with strict tenant & context validation.
# --------------------------------------------------------------

class PaymentOrderService:

    @classmethod
    def generate_order_number(cls) -> str:
        year = timezone.now().strftime('%Y')
        unique = uuid.uuid4().hex[:8].upper()
        return f"ORD-{year}-{unique}"

    @classmethod
    @transaction.atomic
    def create_payment_order(
        cls,
        payment_context: str,
        payer: User,
        academy: Academy = None,
        course: Course = None,
        plan=None,
        add_on=None,
        subtotal_amount: Decimal = None,
        coupon_code: str = None,
        gateway: str = None,
        currency: str = 'USD',
        created_by: User = None,
        return_url: str = None,
        cancel_url: str = None
    ) -> tuple[PaymentOrder, dict]:
        """
        Creates PaymentOrder after validating context rules using configured provider gateway.
        """
        if not gateway:
            gateway = getattr(settings, 'PAYMENT_PROVIDER', 'stripe').upper()

        # Context Validation
        if payment_context == PaymentContext.COURSE_PURCHASE:
            if not course:
                raise ValidationError("Course is required for COURSE_PURCHASE orders.")
            academy = course.academy  # Never trust client-supplied academy!
            subtotal = Decimal(str(course.price)) if subtotal_amount is None else Decimal(str(subtotal_amount))
            course_title_snapshot = course.title
            product_name_snapshot = course.title
        elif payment_context == PaymentContext.PLATFORM_PURCHASE:
            if not academy:
                raise ValidationError("Academy is required for PLATFORM_PURCHASE orders.")
            subtotal = Decimal(str(subtotal_amount or '0.00'))
            course_title_snapshot = ''
            product_name_snapshot = plan.name if plan else (add_on.name if add_on else 'Platform Services')
        else:
            raise ValidationError("Invalid payment_context.")

        pricing = PaymentPricingService.calculate_order_pricing(
            subtotal_amount=subtotal,
            coupon_code=coupon_code,
            user=payer,
            payment_context=payment_context,
            academy=academy,
            course=course
        )

        order_num = cls.generate_order_number()

        order = PaymentOrder.objects.create(
            order_number=order_num,
            payment_context=payment_context,
            academy=academy,
            payer=payer,
            course=course,
            plan=plan,
            add_on=add_on,
            subtotal_amount=pricing['subtotal'],
            discount_amount=pricing['discount'],
            tax_amount=pricing['tax'],
            final_amount=pricing['final_amount'],
            currency=currency,
            course_title_snapshot=course_title_snapshot,
            product_name_snapshot=product_name_snapshot,
            academy_name_snapshot=academy.name if academy else '',
            coupon=pricing['coupon'],
            status=OrderStatus.CREATED,
            gateway=gateway,
            created_by=created_by or payer
        )

        # Create Gateway Order Reference
        gateway_data = PaymentGatewayService.create_gateway_order(order, return_url=return_url, cancel_url=cancel_url)
        order.gateway_order_id = gateway_data.get('gateway_order_id', f"order_{order.id.hex[:16]}")
        order.save(update_fields=['gateway_order_id'])

        return order, gateway_data


# --------------------------------------------------------------
# 5. Payment Fulfillment Service
# Applies business benefits only after verified payment success.
# Never grant access based only on a frontend "payment successful" response.
# Fulfillment must be idempotent so retries cannot create duplicate
# Enrollments, Plan activations, Add-ons, or Credit entries.
# --------------------------------------------------------------

class PaymentFulfillmentService:

    @classmethod
    @transaction.atomic
    def process_successful_payment(
        cls,
        order: PaymentOrder,
        gateway_payment_id: str,
        gateway: str = GatewayType.RAZORPAY,
        payment_method: str = PaymentMethod.OTHER,
        raw_payload: dict = None
    ) -> PaymentOrder:
        """
        Idempotent fulfillment engine for confirmed successful payments.
        """
        # Lock order row for update
        order = PaymentOrder.objects.select_for_update().get(id=order.id)

        if order.status == OrderStatus.COMPLETED:
            return order  # Idempotent safeguard

        now = timezone.now()
        order.status = OrderStatus.COMPLETED
        order.completed_at = now
        order.save(update_fields=['status', 'completed_at'])

        # Create or update transaction record
        transaction_obj, _ = PaymentTransaction.objects.get_or_create(
            order=order,
            gateway_payment_id=gateway_payment_id,
            defaults={
                'payer': order.payer,
                'gateway': gateway,
                'payment_method': payment_method,
                'amount': order.final_amount,
                'currency': order.currency,
                'status': TransactionStatus.SUCCESS,
                'paid_at': now,
                'raw_reference': raw_payload or {}
            }
        )

        # Record Coupon Redemption if coupon was used
        if order.coupon:
            CouponRedemption.objects.get_or_create(
                coupon=order.coupon,
                order=order,
                user=order.payer,
                defaults={
                    'academy': order.academy,
                    'original_amount': order.subtotal_amount,
                    'discount_amount': order.discount_amount,
                    'status': 'REDEEMED'
                }
            )
            order.coupon.current_usage_count += 1
            order.coupon.save(update_fields=['current_usage_count'])

        # Dispatch Business Fulfillment
        if order.payment_context == PaymentContext.COURSE_PURCHASE and order.course and order.payer:
            EnrollmentService.enroll_student(
                student=order.payer,
                course=order.course,
                access_type='FULL',
                source='PURCHASE',
                source_reference=order.order_number
            )
            if order.payer.email:
                EmailService.send_transactional(
                    recipient=order.payer.email,
                    template_code="COURSE_PURCHASE_SUCCESS",
                    subject=f"Course Purchase Confirmed: {order.course.title}",
                    context={'body': f"Payment confirmed for '{order.course.title}'. Access is now unlocked."},
                    user=order.payer,
                    academy=order.academy
                )

        elif order.payment_context == PaymentContext.PLATFORM_PURCHASE and order.academy:
            CreditsService.credit(
                academy=order.academy,
                amount=order.final_amount,
                source_type='PURCHASE',
                idempotency_key=f"PAYMENT_{order.id}",
                description=f"Credits purchased via Payment Order {order.order_number}"
            )

        # Generate Invoice
        InvoiceService.generate_invoice(order)

        return order

    @classmethod
    @transaction.atomic
    def handle_webhook_event(
        cls,
        event_id: str = None,
        gateway: str = "stripe",
        event_type: str = None,
        payload: dict = None,
        signature_valid: bool = True,
        headers: dict = None,
        raw_body: any = None
    ) -> bool:
        """
        Verifies signature and processes gateway webhook event idempotently.
        Supports normalized event processing across payment providers.
        """
        payload = payload or {}

        if raw_body or headers:
            provider = PaymentGatewayService.get_provider(gateway)
            normalized = provider.parse_webhook_event(raw_body or payload, headers or {})
            event_id = event_id or normalized['event_id']
            event_type = event_type or normalized['event_type']
            signature_valid = normalized['signature_valid']
            payload = normalized['raw_payload']

        if not event_id:
            event_id = payload.get('id') or payload.get('event_id') or f"evt_{uuid.uuid4().hex[:12]}"
        if not event_type:
            event_type = payload.get('type') or payload.get('event') or 'payment_intent.succeeded'

        event, created = PaymentWebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                'gateway': gateway,
                'event_type': event_type,
                'signature_valid': signature_valid,
                'payload': payload,
                'processed': False
            }
        )

        if not created and event.processed:
            return True

        if not signature_valid:
            event.error_message = "Invalid gateway signature."
            event.save(update_fields=['error_message'])
            return False

        if event_type in ['payment_intent.succeeded', 'checkout.session.completed', 'payment.captured', 'order.paid', 'payment.authorized']:
            order_id = payload.get('order_id') or payload.get('payment_order_id')
            gw_order_id = None
            if not order_id and isinstance(payload.get('payload'), dict):
                p_entity = payload['payload'].get('payment', {}).get('entity', {})
                gw_order_id = p_entity.get('order_id')
                order_id = p_entity.get('notes', {}).get('order_id')
            elif not order_id and isinstance(payload.get('data'), dict):
                obj = payload['data'].get('object', {})
                order_id = obj.get('metadata', {}).get('order_id') or obj.get('client_reference_id') or obj.get('order_id')

            gw_pay_id = payload.get('payment_id') or payload.get('gateway_payment_id')
            if not gw_pay_id and isinstance(payload.get('payload'), dict):
                p_entity = payload['payload'].get('payment', {}).get('entity', {})
                gw_pay_id = p_entity.get('id')
            if not gw_pay_id and isinstance(payload.get('data'), dict):
                obj = payload['data'].get('object', {})
                gw_pay_id = obj.get('payment_intent') or obj.get('id') or event_id
            if not gw_pay_id:
                gw_pay_id = event_id

            # 1. Try finalizing CreditPurchase if order corresponds to credit package
            from credits.models import CreditPurchase, PurchaseStatus
            from credits.services import CreditPurchaseService
            cp = None
            if gw_order_id:
                cp = CreditPurchase.objects.filter(payment_order_id=gw_order_id).first()
            if not cp and order_id:
                cp = CreditPurchase.objects.filter(payment_order_id=order_id).first()

            if cp:
                CreditPurchaseService.finalize_credit_purchase(
                    payment_order_id=cp.payment_order_id,
                    transaction_id=gw_pay_id,
                    razorpay_order_id=gw_order_id or cp.payment_order_id,
                    source="razorpay_webhook"
                )

            # 2. Process standard course/platform PaymentOrder
            order = None
            if order_id:
                try:
                    order = PaymentOrder.objects.get(id=order_id)
                except (PaymentOrder.DoesNotExist, ValueError):
                    pass
            if not order and gw_order_id:
                order = PaymentOrder.objects.filter(gateway_order_id=gw_order_id).first()

            if order:
                cls.process_successful_payment(order, gateway_payment_id=gw_pay_id, gateway=gateway, raw_payload=payload)

        elif event_type in ['payment.failed', 'payment_intent.payment_failed']:
            gw_order_id = None
            if isinstance(payload.get('payload'), dict):
                p_entity = payload['payload'].get('payment', {}).get('entity', {})
                gw_order_id = p_entity.get('order_id')
            if gw_order_id:
                from credits.models import CreditPurchase, PurchaseStatus
                cp = CreditPurchase.objects.filter(payment_order_id=gw_order_id, status=PurchaseStatus.PENDING).first()
                if cp:
                    cp.status = PurchaseStatus.FAILED
                    cp.save(update_fields=['status'])

                order = PaymentOrder.objects.filter(gateway_order_id=gw_order_id, status=OrderStatus.CREATED).first()
                if order:
                    order.status = OrderStatus.FAILED
                    order.save(update_fields=['status'])

        event.processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=['processed', 'processed_at'])
        return True

# --------------------------------------------------------------
# 6. Refund Service
# Handles full and partial refunds without destroying financial payment history.
# --------------------------------------------------------------

class RefundService:

    @classmethod
    def generate_refund_number(cls) -> str:
        year = timezone.now().strftime('%Y')
        unique = uuid.uuid4().hex[:8].upper()
        return f"REF-{year}-{unique}"

    @classmethod
    @transaction.atomic
    def process_refund(
        cls,
        transaction_obj: PaymentTransaction,
        refund_amount: Decimal = None,
        reason: str = "",
        requested_by: User = None
    ) -> PaymentRefund:
        order = transaction_obj.order
        amount = Decimal(str(refund_amount or order.final_amount)).quantize(Decimal('0.01'))

        # Check total existing refunds
        existing_refunds_total = sum(r.amount for r in order.refunds.filter(status=RefundStatus.SUCCESS))
        if existing_refunds_total + amount > order.final_amount:
            raise ValidationError("Refund amount exceeds the remaining paid total for this order.")

        gw_res = PaymentGatewayService.process_gateway_refund(transaction_obj, amount)

        refund_num = cls.generate_refund_number()
        refund = PaymentRefund.objects.create(
            refund_number=refund_num,
            transaction=transaction_obj,
            order=order,
            amount=amount,
            reason=reason,
            status=RefundStatus.SUCCESS,
            gateway_refund_id=gw_res.get('gateway_refund_id', ''),
            requested_by=requested_by,
            processed_at=timezone.now()
        )

        new_total = existing_refunds_total + amount
        if new_total >= order.final_amount:
            order.status = OrderStatus.REFUNDED
        else:
            order.status = OrderStatus.PARTIALLY_REFUNDED
        order.save(update_fields=['status'])

        return refund

# --------------------------------------------------------------
# 7. Invoice Service
# Generates immutable invoice snapshots.
# --------------------------------------------------------------

class InvoiceService:

    @classmethod
    def generate_invoice_number(cls) -> str:
        year = timezone.now().strftime('%Y')
        unique = uuid.uuid4().hex[:8].upper()
        return f"INV-{year}-{unique}"

    @classmethod
    @transaction.atomic
    def generate_invoice(cls, order: PaymentOrder) -> PaymentInvoice:
        if hasattr(order, 'invoice'):
            return order.invoice

        inv_num = cls.generate_invoice_number()
        invoice = PaymentInvoice.objects.create(
            order=order,
            invoice_number=inv_num,
            seller_name_snapshot=order.academy.name if order.academy else "CubixSkill Platform",
            buyer_name_snapshot=order.payer.full_name if order.payer else "Valued Customer",
            subtotal_amount=order.subtotal_amount,
            discount_amount=order.discount_amount,
            tax_amount=order.tax_amount,
            total_amount=order.final_amount,
            currency=order.currency,
            status='ISSUED'
        )

        return invoice
