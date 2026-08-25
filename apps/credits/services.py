import uuid
import math
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from users_roles.models import User
from credits.models import (
    CreditAccount,
    CreditLedgerEntry,
    CreditAdjustment,
    CreditRate,
    CreditPackage,
    CreditPurchaseCoupon,
    CreditPurchase,
    StorageCreditCharge,
    CreditAccountStatus,
    LedgerEntryType,
    CreditSourceType,
    AdjustmentType,
    AdjustmentStatus,
    BillingType,
    CouponDiscountType,
    PurchaseStatus,
)
from core.exceptions import CubixSkillAPIException

LOW_BALANCE_THRESHOLD = Decimal('100.000000')

# --------------------------------------------------------------
# 1. Credit Pricing Service
# Super Admin configurable pricing rates for platform features.
# --------------------------------------------------------------

class CreditPricingService:

    DEFAULT_RATES = [
        {
            'feature_key': 'CREDIT_PURCHASE_500',
            'name': '500 Credits',
            'description': 'Starter Credit Pack for small academies.',
            'billing_type': BillingType.FIXED,
            'unit_size': Decimal('1.0000'),
            'credit_cost': Decimal('500.0000'),
            'price': Decimal('499.00'),
            'credits': Decimal('500.000000'),
            'currency': 'INR',
            'is_purchasable': True,
            'is_active': True,
        },
        {
            'feature_key': 'CREDIT_PURCHASE_1000',
            'name': '1000 Credits',
            'description': 'Standard Credit Pack for growing academies.',
            'billing_type': BillingType.FIXED,
            'unit_size': Decimal('1.0000'),
            'credit_cost': Decimal('1000.0000'),
            'price': Decimal('899.00'),
            'credits': Decimal('1000.000000'),
            'currency': 'INR',
            'is_purchasable': True,
            'is_active': True,
        },
        {
            'feature_key': 'CREDIT_PURCHASE_2500',
            'name': '2500 Credits',
            'description': 'Value Credit Pack for established institutions.',
            'billing_type': BillingType.FIXED,
            'unit_size': Decimal('1.0000'),
            'credit_cost': Decimal('2500.0000'),
            'price': Decimal('1999.00'),
            'credits': Decimal('2500.000000'),
            'currency': 'INR',
            'is_purchasable': True,
            'is_active': True,
        },
        {
            'feature_key': 'EMAIL_SEND',
            'name': 'Email Sending Service',
            'description': 'Credit cost per billable recipient email sent.',
            'billing_type': BillingType.PER_UNIT,
            'unit_size': Decimal('1.0000'),
            'credit_cost': Decimal('1.0000'),
            'price': Decimal('0.00'),
            'credits': Decimal('0.000000'),
            'currency': 'INR',
            'is_purchasable': False,
            'is_active': True,
        },
        {
            'feature_key': 'STORAGE_MONTHLY',
            'name': 'Monthly Cloud Storage',
            'description': 'Credit cost per GB of stored academy media/files per month.',
            'billing_type': BillingType.PER_UNIT,
            'unit_size': Decimal('1.0000'),
            'credit_cost': Decimal('10.0000'),
            'price': Decimal('0.00'),
            'credits': Decimal('0.000000'),
            'currency': 'INR',
            'is_purchasable': False,
            'is_active': True,
        },
    ]

    @classmethod
    def ensure_default_rates(cls):
        # Default mock rates seeding disabled so Super Admin has total control over rates in database
        pass

    @classmethod
    def list_purchasable_rates(cls):
        return CreditRate.objects.filter(
            is_active=True,
            is_purchasable=True
        ).order_by('price')

    @classmethod
    def get_rate(cls, feature_key: str) -> CreditRate:
        cls.ensure_default_rates()
        rate = CreditRate.objects.filter(feature_key=feature_key, is_active=True).first()
        if not rate:
            return CreditRate(
                feature_key=feature_key,
                name=feature_key,
                billing_type=BillingType.PER_UNIT,
                unit_size=Decimal('1.0000'),
                credit_cost=Decimal('1.0000')
            )
        return rate

    @classmethod
    def calculate_email_cost(cls, recipient_count: int) -> Decimal:
        if recipient_count <= 0:
            return Decimal('0.000000')
        rate = cls.get_rate('EMAIL_SEND')
        units = Decimal(str(recipient_count))
        cost = (units / rate.unit_size) * rate.credit_cost
        return cost.quantize(Decimal('0.000001'))

    @classmethod
    def calculate_storage_cost(cls, usage_bytes: int) -> tuple[Decimal, Decimal]:
        if usage_bytes <= 0:
            return Decimal('0.0000'), Decimal('0.000000')
        rate = cls.get_rate('STORAGE_MONTHLY')
        bytes_in_gb = Decimal('1073741824') # 1 GB
        gb_units = (Decimal(str(usage_bytes)) / bytes_in_gb).quantize(Decimal('0.0001'))
        if gb_units <= Decimal('0.0000'):
            gb_units = Decimal('0.0001')
        cost = (gb_units / rate.unit_size) * rate.credit_cost
        return gb_units, cost.quantize(Decimal('0.000001'))

    @classmethod
    def calculate_course_per_student_pricing(cls, course) -> dict:
        """
        Calculates per-student credit price for a course based on Base Student Access + enabled features.
        Authoritative formula: Total = Base + SUM(enabled billable feature credit rates).
        """
        if not course:
            return {
                "base_credits_per_student": 1,
                "total_credits_per_student": 1,
                "enabled_features_count": 0,
                "breakdown": []
            }

        from control_panel.models import PricingRule
        from features.services import CourseFeatureService

        pricing_rules = {
            pr.code.strip().upper(): pr for pr in PricingRule.objects.filter(is_active=True)
        }

        base_rule = pricing_rules.get('STUDENT_BASE') or pricing_rules.get('COURSE_BASE')
        base_credits = int(base_rule.credit_cost) if base_rule else 15

        breakdown = [{
            "key": "STUDENT_BASE",
            "name": "Student Base Price",
            "credits_per_student": base_credits,
            "is_base": True,
            "enabled": True
        }]

        features = CourseFeatureService.get_features(course)
        enabled_features_count = 0
        feature_credits_sum = 0
        per_student_codes = {'LESSONS', 'FEE_COLLECTION', 'LIVE_CLASS', 'COURSE_DISCUSSION', 'ONE_TO_ONE_SESSION'}

        for f in features:
            is_enabled = f.get('effective_enabled', False) or f.get('is_enabled', False)
            is_per_student = f.get('is_per_student', False) or f.get('code') in per_student_codes or f.get('billing_unit') == 'PER_STUDENT'

            if is_enabled:
                enabled_features_count += 1
                if is_per_student:
                    cost = f.get('credit_cost', 0)
                    feature_credits_sum += cost
                    if cost > 0:
                        breakdown.append({
                            "key": f['code'],
                            "name": f['name'],
                            "credits_per_student": cost,
                            "is_base": False,
                            "enabled": True
                        })

        total_credits = base_credits + feature_credits_sum

        return {
            "student_base_price": str(Decimal(base_credits).quantize(Decimal('0.000000'))),
            "feature_student_total": str(Decimal(feature_credits_sum).quantize(Decimal('0.000000'))),
            "total_per_student": str(Decimal(total_credits).quantize(Decimal('0.000000'))),
            "base_credits_per_student": base_credits,
            "feature_credits_sum": feature_credits_sum,
            "total_credits_per_student": total_credits,
            "enabled_features_count": enabled_features_count,
            "breakdown": breakdown
        }


# --------------------------------------------------------------
# 2. Credit Package Service
# --------------------------------------------------------------

class CreditPackageService:

    DEFAULT_PACKAGES = [
        {
            'name': 'Starter Pack',
            'description': 'Ideal for individual instructors and small cohorts.',
            'credits': Decimal('1000.000000'),
            'price': Decimal('1999.00'),
            'currency': 'INR',
            'bonus_credits': Decimal('0.000000'),
            'popular': False,
            'sort_order': 1,
        },
        {
            'name': 'Pro Growth',
            'description': 'Our most popular bundle for growing academies.',
            'credits': Decimal('5000.000000'),
            'price': Decimal('7999.00'),
            'currency': 'INR',
            'bonus_credits': Decimal('500.000000'),
            'popular': True,
            'sort_order': 2,
        },
        {
            'name': 'Business Scale',
            'description': 'Designed for established organizations with high email and storage needs.',
            'credits': Decimal('15000.000000'),
            'price': Decimal('19999.00'),
            'currency': 'INR',
            'bonus_credits': Decimal('2500.000000'),
            'popular': False,
            'sort_order': 3,
        },
        {
            'name': 'Enterprise Unlimited',
            'description': 'Maximum volume discount for multi-course institutions.',
            'credits': Decimal('50000.000000'),
            'price': Decimal('49999.00'),
            'currency': 'INR',
            'bonus_credits': Decimal('10000.000000'),
            'popular': False,
            'sort_order': 4,
        },
    ]

    @classmethod
    def ensure_default_packages(cls):
        if not CreditPackage.objects.exists():
            for pkg in cls.DEFAULT_PACKAGES:
                CreditPackage.objects.create(**pkg)

    @classmethod
    def list_active_packages(cls):
        cls.ensure_default_packages()
        return CreditPackage.objects.filter(is_active=True).order_by('sort_order', 'price')


# --------------------------------------------------------------
# 3. Credit Coupon Service
# --------------------------------------------------------------

class CreditCouponService:

    DEFAULT_COUPONS = [
        {
            'code': 'CUBIX20',
            'description': '20% Off Season Discount',
            'discount_type': CouponDiscountType.PERCENTAGE,
            'discount_value': Decimal('20.00'),
            'min_purchase_amount': Decimal('1000.00'),
        },
        {
            'code': 'WELCOME10',
            'description': '10% New Instructor Bonus',
            'discount_type': CouponDiscountType.PERCENTAGE,
            'discount_value': Decimal('10.00'),
            'min_purchase_amount': Decimal('500.00'),
        },
        {
            'code': 'FESTIVE500',
            'description': 'INR 500 Flat Savings',
            'discount_type': CouponDiscountType.FIXED_AMOUNT,
            'discount_value': Decimal('500.00'),
            'min_purchase_amount': Decimal('3000.00'),
        },
    ]

    @classmethod
    def ensure_default_coupons(cls):
        for c in cls.DEFAULT_COUPONS:
            CreditPurchaseCoupon.objects.get_or_create(code=c['code'], defaults=c)

    @classmethod
    def validate_coupon(cls, code: str, raw_price: Decimal, academy: Academy = None) -> tuple[CreditPurchaseCoupon, Decimal]:
        cls.ensure_default_coupons()
        if not code or not code.strip():
            raise ValidationError({"coupon": "Coupon code is required."})

        code_upper = code.strip().upper()
        coupon = CreditPurchaseCoupon.objects.filter(code=code_upper, is_active=True).first()
        if not coupon:
            raise ValidationError({"coupon": f"Coupon code '{code_upper}' is invalid or expired."})

        now = timezone.now()
        if coupon.valid_from and coupon.valid_from > now:
            raise ValidationError({"coupon": f"Coupon '{code_upper}' is not active yet."})
        if coupon.valid_until and coupon.valid_until < now:
            raise ValidationError({"coupon": f"Coupon '{code_upper}' has expired."})

        if coupon.usage_limit is not None and coupon.current_usage_count >= coupon.usage_limit:
            raise ValidationError({"coupon": f"Coupon '{code_upper}' usage limit has been reached."})

        if raw_price < coupon.min_purchase_amount:
            raise ValidationError({"coupon": f"Minimum purchase amount for coupon '{code_upper}' is INR {coupon.min_purchase_amount}."})

        discount_amount = Decimal('0.00')
        if coupon.discount_type == CouponDiscountType.PERCENTAGE:
            discount_amount = (raw_price * (coupon.discount_value / Decimal('100.00'))).quantize(Decimal('0.01'))
            if coupon.max_discount_amount and discount_amount > coupon.max_discount_amount:
                discount_amount = coupon.max_discount_amount
        elif coupon.discount_type == CouponDiscountType.FIXED_AMOUNT:
            discount_amount = min(coupon.discount_value, raw_price)

        return coupon, discount_amount


# --------------------------------------------------------------
# 4. Credit Purchase Service
# --------------------------------------------------------------

class CreditPurchaseService:

    @classmethod
    @transaction.atomic
    def create_purchase_order(
        cls,
        academy: Academy,
        rate_id: str = None,
        package_id: str = None,
        coupon_code: str = "",
        user: User = None
    ) -> CreditPurchase:
        rate = None
        package = None

        if rate_id:
            try:
                rate = CreditRate.objects.get(pk=rate_id, is_active=True, is_purchasable=True)
            except CreditRate.DoesNotExist:
                raise ValidationError({"rate_id": "Selected credit rate option is unavailable or inactive."})
            raw_price = rate.price
            base_credits = rate.credits if rate.credits > 0 else (rate.credit_cost if rate.credit_cost > 0 else Decimal('100.000000'))
            bonus_credits = Decimal('0.000000')
            from core.utils import normalize_currency
            currency = normalize_currency(rate.currency)
            product_name = f"Credit Rate: {rate.name} ({int(base_credits)} Credits)"
        elif package_id:
            try:
                package = CreditPackage.objects.get(pk=package_id, is_active=True)
            except CreditPackage.DoesNotExist:
                raise ValidationError({"package_id": "Selected credit package is unavailable."})
            raw_price = package.price
            base_credits = package.credits
            bonus_credits = package.bonus_credits
            from core.utils import normalize_currency
            currency = normalize_currency(package.currency)
            product_name = f"Credit Package: {package.name} ({package.credits} Credits)"
        else:
            raise ValidationError({"rate_id": "Either rate_id or package_id must be provided."})

        coupon = None
        discount_amount = Decimal('0.00')

        if coupon_code and coupon_code.strip():
            coupon, discount_amount = CreditCouponService.validate_coupon(coupon_code, raw_price, academy)

        final_price = max(raw_price - discount_amount, Decimal('0.00'))

        order_id = f"CP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

        purchase = CreditPurchase.objects.create(
            academy=academy,
            rate=rate,
            package=package,
            coupon=coupon,
            base_credits=base_credits,
            bonus_credits=bonus_credits,
            total_credits=base_credits + bonus_credits,
            original_price=raw_price,
            discount_amount=discount_amount,
            final_price=final_price,
            currency=currency,
            payment_order_id=order_id,
            status=PurchaseStatus.PENDING,
            created_by=user
        )
        from payments.models import PaymentOrder, OrderStatus
        from payments.services import PaymentGatewayService, PaymentOrderService
        
        # Build underlying PaymentOrder for gateway handling
        order_number = PaymentOrderService.generate_order_number()
        payment_order = PaymentOrder.objects.create(
            order_number=order_number,
            payment_context='PLATFORM_PURCHASE',
            academy=academy,
            payer=user,
            currency=currency,
            subtotal_amount=raw_price,
            discount_amount=discount_amount,
            tax_amount=Decimal('0.00'),
            final_amount=final_price,
            product_name_snapshot=product_name,
            academy_name_snapshot=academy.name if academy else '',
            gateway='RAZORPAY',
            status=OrderStatus.CREATED,
            created_by=user
        )

        provider_order_data = PaymentGatewayService.create_gateway_order(payment_order)
        gateway_order_id = provider_order_data.get('gateway_order_id', f"order_{purchase.id.hex[:16]}")

        payment_order.gateway_order_id = gateway_order_id
        payment_order.save(update_fields=['gateway_order_id'])

        purchase.payment_order_id = gateway_order_id
        purchase.save(update_fields=['payment_order_id'])

        return purchase, provider_order_data

    @classmethod
    @transaction.atomic
    def finalize_credit_purchase(
        cls,
        payment_order_id: str,
        transaction_id: str = "",
        razorpay_order_id: str = "",
        source: str = "frontend_verify"
    ) -> tuple[CreditPurchase, bool]:
        """
        Single canonical shared finalization service for Credit Purchases.
        Used by both frontend POST /verify/ and Razorpay Webhook.
        Idempotent: adds credits to academy wallet ONLY once.
        Returns (CreditPurchase, already_processed_boolean).
        """
        from payments.models import PaymentOrder, OrderStatus, PaymentTransaction, TransactionStatus

        lookup_id = razorpay_order_id or payment_order_id
        try:
            purchase = CreditPurchase.objects.select_for_update().get(payment_order_id=lookup_id)
        except CreditPurchase.DoesNotExist:
            purchase = CreditPurchase.objects.select_for_update().filter(payment_order_id=payment_order_id).first()
            if not purchase:
                raise ValidationError({"detail": "Credit purchase order not found."})

        if razorpay_order_id and purchase.payment_order_id != razorpay_order_id:
            raise ValidationError({"detail": "Payment order does not match this purchase."})

        if purchase.status == PurchaseStatus.FULFILLED or purchase.status == PurchaseStatus.PAID:
            # Already fulfilled idempotently
            return purchase, True

        idempotency_key = f"purchase_fulfillment:{purchase.payment_order_id}"

        ledger_entry = CreditsService.credit(
            academy=purchase.academy,
            amount=purchase.total_credits,
            source_type=CreditSourceType.PURCHASE,
            idempotency_key=idempotency_key,
            description=f"Purchased {purchase.rate.name if purchase.rate else (purchase.package.name if purchase.package else 'Credit Bundle')}",
            reference_type="CREDIT_PURCHASE",
            reference_id=str(purchase.id),
            created_by=purchase.created_by,
            metadata={
                "payment_order_id": purchase.payment_order_id,
                "transaction_id": transaction_id,
                "base_credits": str(purchase.base_credits),
                "bonus_credits": str(purchase.bonus_credits),
                "final_price": str(purchase.final_price),
                "source": source,
            }
        )

        purchase.status = PurchaseStatus.FULFILLED
        purchase.payment_transaction_id = transaction_id or f"TX-{uuid.uuid4().hex[:10].upper()}"
        purchase.fulfilled_at = timezone.now()
        purchase.ledger_entry = ledger_entry
        purchase.save(update_fields=['status', 'payment_transaction_id', 'fulfilled_at', 'ledger_entry'])

        # Update linked PaymentOrder status and PaymentTransaction
        payment_order = PaymentOrder.objects.select_for_update().filter(gateway_order_id=purchase.payment_order_id).first()
        if payment_order:
            payment_order.status = OrderStatus.COMPLETED
            payment_order.completed_at = timezone.now()
            payment_order.save(update_fields=['status', 'completed_at'])

            PaymentTransaction.objects.get_or_create(
                order=payment_order,
                gateway_payment_id=transaction_id or f"pay_{uuid.uuid4().hex[:14]}",
                defaults={
                    'gateway': 'RAZORPAY',
                    'status': TransactionStatus.SUCCESS,
                    'amount': purchase.final_price,
                    'currency': purchase.currency,
                    'raw_reference': {'status': 'captured', 'transaction_id': transaction_id, 'source': source}
                }
            )

        if purchase.coupon:
            purchase.coupon.current_usage_count += 1
            purchase.coupon.save(update_fields=['current_usage_count'])

        return purchase, False

    @classmethod
    def fulfill_purchase(cls, payment_order_id: str, transaction_id: str = "") -> CreditPurchase:
        purchase, _ = cls.finalize_credit_purchase(payment_order_id=payment_order_id, transaction_id=transaction_id)
        return purchase


# --------------------------------------------------------------
# 5. Core Credits Service (Wallet Mutations)
# --------------------------------------------------------------

class CreditsService:

    @classmethod
    def get_or_create_account(cls, academy: Academy) -> CreditAccount:
        if not academy:
            academy = Academy.objects.first()
            if not academy:
                academy = Academy.objects.create(name="Default Academy", slug="default-academy")
        account, _ = CreditAccount.objects.get_or_create(academy=academy)
        return account

    @classmethod
    def get_balance(cls, academy: Academy) -> Decimal:
        account = cls.get_or_create_account(academy)
        return account.balance

    @classmethod
    def is_low_balance(cls, academy: Academy) -> bool:
        balance = cls.get_balance(academy)
        return balance < LOW_BALANCE_THRESHOLD

    @classmethod
    @transaction.atomic
    def credit(
        cls,
        academy: Academy,
        amount: Decimal,
        source_type: str,
        idempotency_key: str,
        description: str = "",
        reference_type: str = "",
        reference_id: str = "",
        created_by: User = None,
        metadata: dict = None
    ) -> CreditLedgerEntry:
        """
        Increases Academy credit balance atomically and appends an immutable ledger entry.
        Idempotent operation using database-level uniqueness constraint.
        """
        amount = Decimal(str(amount)).quantize(Decimal('0.000001'))
        if amount <= Decimal('0.000000'):
            raise ValidationError({"amount": "Credit amount must be positive."})

        # Idempotency check
        existing = CreditLedgerEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        account = CreditAccount.objects.select_for_update().get(id=cls.get_or_create_account(academy).id)
        balance_before = account.balance
        balance_after = balance_before + amount

        now = timezone.now()
        account.balance = balance_after
        account.total_credited += amount
        account.last_transaction_at = now
        account.save(update_fields=['balance', 'total_credited', 'last_transaction_at'])

        entry = CreditLedgerEntry.objects.create(
            account=account,
            entry_type=LedgerEntryType.CREDIT,
            source_type=source_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=str(reference_id),
            idempotency_key=idempotency_key,
            description=description or f"Credited {amount} ({source_type})",
            metadata=metadata or {},
            created_by=created_by,
            occurred_at=now
        )

        return entry

    @classmethod
    @transaction.atomic
    def debit(
        cls,
        academy: Academy,
        amount: Decimal,
        source_type: str,
        idempotency_key: str,
        description: str = "",
        reference_type: str = "",
        reference_id: str = "",
        created_by: User = None,
        metadata: dict = None,
        allow_negative: bool = False
    ) -> CreditLedgerEntry:
        """
        Decreases Academy credit balance atomically and appends an immutable ledger entry.
        """
        amount = Decimal(str(amount)).quantize(Decimal('0.000001'))
        if amount <= Decimal('0.000000'):
            raise ValidationError({"amount": "Debit amount must be positive."})

        # Idempotency check
        existing = CreditLedgerEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        account = CreditAccount.objects.select_for_update().get(id=cls.get_or_create_account(academy).id)

        if account.status == CreditAccountStatus.SUSPENDED and not allow_negative:
            raise CubixSkillAPIException("Credit account is suspended.", code="CREDIT_ACCOUNT_SUSPENDED", status_code=403)

        balance_before = account.balance

        if not allow_negative and balance_before < amount:
            raise CubixSkillAPIException(
                f"Insufficient credits for this operation. Required: {amount}, Available: {balance_before}",
                code="INSUFFICIENT_CREDITS",
                status_code=400
            )

        balance_after = balance_before - amount
        now = timezone.now()

        account.balance = balance_after
        account.total_debited += amount
        account.last_transaction_at = now
        account.save(update_fields=['balance', 'total_debited', 'last_transaction_at'])

        entry = CreditLedgerEntry.objects.create(
            account=account,
            entry_type=LedgerEntryType.DEBIT,
            source_type=source_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=str(reference_id),
            idempotency_key=idempotency_key,
            description=description or f"Debited {amount} ({source_type})",
            metadata=metadata or {},
            created_by=created_by,
            occurred_at=now
        )

        return entry

    @classmethod
    @transaction.atomic
    def deduct_email_credits(
        cls,
        academy: Academy,
        recipient_count: int,
        reference_id: str = "",
        description: str = "",
        created_by: User = None
    ) -> CreditLedgerEntry:
        """
        Deducts credits for billable emails based on Super Admin configured rate.
        Calculated backend-side.
        """
        required_credits = CreditPricingService.calculate_email_cost(recipient_count)
        if required_credits <= Decimal('0.000000'):
            return None

        idempotency_key = f"email_send:{reference_id or uuid.uuid4().hex}:{recipient_count}"
        desc = description or f"Sent {recipient_count} email notification(s)"

        return cls.debit(
            academy=academy,
            amount=required_credits,
            source_type=CreditSourceType.EMAIL_USAGE,
            idempotency_key=idempotency_key,
            description=desc,
            reference_type="EMAIL_SEND",
            reference_id=str(reference_id),
            created_by=created_by,
            metadata={"recipient_count": recipient_count, "rate_per_email": str(CreditPricingService.get_rate('EMAIL_SEND').credit_cost)}
        )

    @classmethod
    @transaction.atomic
    def charge_monthly_storage(
        cls,
        academy: Academy,
        usage_bytes: int,
        billing_period: str
    ) -> StorageCreditCharge:
        """
        Idempotently calculates and charges monthly storage credits.
        """
        existing = StorageCreditCharge.objects.filter(academy=academy, billing_period=billing_period).first()
        if existing:
            return existing

        gb_units, required_credits = CreditPricingService.calculate_storage_cost(usage_bytes)
        rate = CreditPricingService.get_rate('STORAGE_MONTHLY')

        ledger_entry = None
        if required_credits > Decimal('0.000000'):
            idempotency_key = f"storage_billing:{academy.id}:{billing_period}"
            ledger_entry = cls.debit(
                academy=academy,
                amount=required_credits,
                source_type=CreditSourceType.STORAGE_USAGE,
                idempotency_key=idempotency_key,
                description=f"Monthly cloud storage usage ({gb_units} GB for {billing_period})",
                reference_type="STORAGE_BILLING",
                reference_id=billing_period,
                allow_negative=True,
                metadata={"usage_bytes": usage_bytes, "gb_units": str(gb_units), "billing_period": billing_period}
            )

        charge = StorageCreditCharge.objects.create(
            academy=academy,
            billing_period=billing_period,
            usage_bytes=usage_bytes,
            billable_units_gb=gb_units,
            credit_rate=rate.credit_cost,
            credits_charged=required_credits,
            ledger_entry=ledger_entry,
            status='CHARGED'
        )

        return charge

    @classmethod
    @transaction.atomic
    def adjust(
        cls,
        academy: Academy,
        amount: Decimal,
        adjustment_type: str,
        reason: str,
        requested_by: User = None,
        approved_by: User = None
    ) -> CreditAdjustment:
        """
        Executes Super Admin manual credit addition or deduction with audit record.
        """
        amount = Decimal(str(amount)).quantize(Decimal('0.000001'))
        if amount <= Decimal('0.000000'):
            raise ValidationError({"amount": "Adjustment amount must be positive."})

        account = cls.get_or_create_account(academy)
        idempotency_key = f"adjustment:{uuid.uuid4().hex}"

        adjustment = CreditAdjustment.objects.create(
            account=account,
            adjustment_type=adjustment_type,
            amount=amount,
            reason=reason,
            status=AdjustmentStatus.APPROVED,
            requested_by=requested_by,
            approved_by=approved_by or requested_by
        )

        if adjustment_type == AdjustmentType.ADD:
            entry = cls.credit(
                academy=academy,
                amount=amount,
                source_type=CreditSourceType.MANUAL_ADJUSTMENT,
                idempotency_key=idempotency_key,
                description=f"Manual credit addition: {reason}",
                reference_type="CREDIT_ADJUSTMENT",
                reference_id=str(adjustment.id),
                created_by=requested_by
            )
        elif adjustment_type == AdjustmentType.DEDUCT:
            entry = cls.debit(
                academy=academy,
                amount=amount,
                source_type=CreditSourceType.MANUAL_ADJUSTMENT,
                idempotency_key=idempotency_key,
                description=f"Manual credit deduction: {reason}",
                reference_type="CREDIT_ADJUSTMENT",
                reference_id=str(adjustment.id),
                created_by=requested_by,
                allow_negative=True
            )
        else:
            raise ValidationError({"adjustment_type": "Invalid adjustment type."})

        adjustment.ledger_entry = entry
        adjustment.save(update_fields=['ledger_entry'])

        return adjustment

    @classmethod
    @transaction.atomic
    def reverse_entry(cls, entry_id: str, reason: str, performed_by: User = None) -> CreditLedgerEntry:
        """
        Reverses a finalized ledger entry via a compensating entry. Never edits history.
        """
        try:
            target_entry = CreditLedgerEntry.objects.get(id=entry_id)
        except CreditLedgerEntry.DoesNotExist:
            raise ValidationError({"entry_id": "Ledger entry not found."})

        reversal_key = f"reversal:{target_entry.id}"
        academy = target_entry.account.academy

        if target_entry.entry_type == LedgerEntryType.CREDIT:
            compensating_entry = cls.debit(
                academy=academy,
                amount=target_entry.amount,
                source_type=CreditSourceType.REVERSAL,
                idempotency_key=reversal_key,
                description=f"Reversal of Credit entry {target_entry.id}: {reason}",
                reference_type="CREDIT_LEDGER_ENTRY",
                reference_id=str(target_entry.id),
                created_by=performed_by,
                allow_negative=True
            )
        else:
            compensating_entry = cls.credit(
                academy=academy,
                amount=target_entry.amount,
                source_type=CreditSourceType.REVERSAL,
                idempotency_key=reversal_key,
                description=f"Reversal of Debit entry {target_entry.id}: {reason}",
                reference_type="CREDIT_LEDGER_ENTRY",
                reference_id=str(target_entry.id),
                created_by=performed_by
            )

        return compensating_entry

    @classmethod
    def reconcile_account(cls, academy: Academy) -> tuple[bool, Decimal, Decimal]:
        """
        Reconciles sum(CREDIT) - sum(DEBIT) against cached CreditAccount.balance.
        """
        account = cls.get_or_create_account(academy)

        credits_sum = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.CREDIT
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.000000')

        debits_sum = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.DEBIT
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.000000')

        expected_balance = (credits_sum - debits_sum).quantize(Decimal('0.000001'))
        actual_balance = account.balance.quantize(Decimal('0.000001'))

        is_valid = (expected_balance == actual_balance)
        return is_valid, expected_balance, actual_balance


CreditService = CreditsService
