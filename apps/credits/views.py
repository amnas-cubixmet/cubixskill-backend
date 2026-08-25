import re
from decimal import Decimal
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied

def normalize_indian_phone(phone: str) -> str:
    if not phone:
        return ""
    clean = re.sub(r'[\s\-\(\)]', '', str(phone).strip())
    if not clean:
        return ""
    if clean.startswith('+'):
        return clean
    if clean.startswith('91') and len(clean) == 12:
        return f"+{clean}"
    if clean.startswith('0') and len(clean) == 11:
        return f"+91{clean[1:]}"
    if len(clean) == 10:
        return f"+91{clean}"
    return f"+91{clean}"


from academy.models import Academy
from credits.models import (
    CreditAccount,
    CreditLedgerEntry,
    CreditRate,
    CreditPackage,
    CreditPurchaseCoupon,
    CreditPurchase,
)
from credits.selectors import CreditSelector
from credits.services import (
    CreditsService,
    CreditPricingService,
    CreditPackageService,
    CreditCouponService,
    CreditPurchaseService,
)
from credits.serializers import (
    CreditAccountSerializer,
    CreditLedgerEntrySerializer,
    CreditRateSerializer,
    CreditPackageSerializer,
    CreditPurchaseCouponSerializer,
    CreditPurchaseSerializer,
    CreatePurchaseRequestSerializer,
    ApplyCouponRequestSerializer,
    FulfillPurchaseRequestSerializer,
    CreditAdjustmentSerializer,
    ManualAdjustmentRequestSerializer,
    ReversalRequestSerializer,
)
from core.permissions import IsSuperAdminOrStaff

# --------------------------------------------------------------
# 1. Staff Credit Wallet Endpoints
# --------------------------------------------------------------

class CreditBalanceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError({"academy": "User must belong to an Academy to access credit balance."})

        balance_data = CreditSelector.get_account_balance(academy)
        return Response(balance_data, status=status.HTTP_200_OK)

class CreditLedgerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CreditLedgerEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        if not academy:
            return CreditLedgerEntry.objects.none()

        return CreditSelector.get_academy_ledger(
            academy=academy,
            entry_type=self.request.query_params.get('entry_type'),
            source_type=self.request.query_params.get('source_type'),
            date_from=self.request.query_params.get('date_from'),
            date_to=self.request.query_params.get('date_to')
        )

class CreditSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError({"academy": "User must belong to an Academy to access credit summary."})

        summary_data = CreditSelector.get_academy_summary(academy)
        return Response(summary_data, status=status.HTTP_200_OK)

class CreditUsageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError({"academy": "User must belong to an Academy to access credit usage."})

        breakdown = CreditSelector.get_usage_breakdown(academy)
        return Response({"usage": breakdown}, status=status.HTTP_200_OK)

class CreditPurchaseRatesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rates = CreditPricingService.list_purchasable_rates()
        serializer = CreditRateSerializer(rates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class CreditPackageListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rates = CreditPricingService.list_purchasable_rates()
        serializer = CreditRateSerializer(rates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class CreditPurchaseViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CreditPurchaseSerializer

    def get_queryset(self):
        academy = getattr(self.request.user, 'academy', None)
        if not academy:
            return CreditPurchase.objects.none()
        return CreditPurchase.objects.filter(academy=academy)

    def list(self, request):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='apply-coupon')
    def apply_coupon(self, request):
        return self.purchase_preview(request)

    @action(detail=False, methods=['post'], url_path='purchase-preview')
    def purchase_preview(self, request):
        serializer = ApplyCouponRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        academy = getattr(request.user, 'academy', None)
        rate_id = serializer.validated_data.get('rate_id')
        package_id = serializer.validated_data.get('package_id')
        coupon_code = serializer.validated_data.get('coupon_code', '')

        rate = None
        package = None
        raw_price = Decimal('0.00')
        credits_count = Decimal('0.00')
        currency = 'INR'

        if rate_id:
            try:
                rate = CreditRate.objects.get(pk=rate_id, is_active=True, is_purchasable=True)
                raw_price = rate.price
                credits_count = rate.credits if rate.credits > 0 else rate.credit_cost
                currency = rate.currency
            except CreditRate.DoesNotExist:
                raise ValidationError({"rate_id": "Selected credit rate option is invalid or inactive."})
        elif package_id:
            try:
                package = CreditPackage.objects.get(pk=package_id, is_active=True)
                raw_price = package.price
                credits_count = package.credits + package.bonus_credits
                currency = package.currency
            except CreditPackage.DoesNotExist:
                raise ValidationError({"package_id": "Selected credit package not found."})
        else:
            raise ValidationError({"rate_id": "Either rate_id or package_id is required."})

        discount_amount = Decimal('0.00')
        coupon_obj = None
        if coupon_code and coupon_code.strip():
            coupon_obj, discount_amount = CreditCouponService.validate_coupon(coupon_code, raw_price, academy)

        final_price = max(raw_price - discount_amount, Decimal('0.00'))

        return Response({
            "valid": True,
            "rate_id": str(rate.id) if rate else "",
            "package_id": str(package.id) if package else "",
            "coupon_code": coupon_obj.code if coupon_obj else "",
            "description": coupon_obj.description if coupon_obj else "",
            "discount_type": coupon_obj.discount_type if coupon_obj else "",
            "discount_value": str(coupon_obj.discount_value) if coupon_obj else "0.00",
            "original_price": str(raw_price),
            "discount_amount": str(discount_amount),
            "final_price": str(final_price),
            "credits": str(credits_count),
            "bonus_credits": "0.000000",
            "total_credits": str(credits_count),
            "currency": currency,
        })

    @action(detail=False, methods=['post'], url_path='create-order')
    def create_order(self, request):
        serializer = CreatePurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        academy = getattr(request.user, 'academy', None)
        if not academy and hasattr(request.user, 'academy_memberships'):
            membership = request.user.academy_memberships.first()
            if membership:
                academy = membership.academy
        if not academy:
            account = CreditsService.get_or_create_account(None)
            academy = account.academy

        rate_id = serializer.validated_data.get('rate_id')
        package_id = serializer.validated_data.get('package_id')
        coupon_code = serializer.validated_data.get('coupon_code', '')

        if not rate_id and not package_id:
            raise ValidationError({"detail": "Either rate_id or package_id must be provided."})

        try:
            purchase, gateway_data = CreditPurchaseService.create_purchase_order(
                academy=academy,
                rate_id=str(rate_id) if rate_id else None,
                package_id=str(package_id) if package_id else None,
                coupon_code=coupon_code,
                user=request.user
            )
        except ValidationError as val_err:
            raise val_err
        except Exception as err:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in CreditPurchaseService.create_purchase_order: {err}", exc_info=True)
            raise ValidationError({"detail": "Unable to initialize payment gateway order. Please try again."})

        data = CreditPurchaseSerializer(purchase).data
        data['razorpay_order_id'] = gateway_data.get('gateway_order_id')
        data['key_id'] = gateway_data.get('key_id') or getattr(settings, 'RAZORPAY_KEY_ID', '')
        data['gateway_data'] = gateway_data

        user_phone = getattr(request.user, 'phone', '') or (getattr(academy, 'phone', '') if academy else '')
        data['customer'] = {
            'name': getattr(request.user, 'full_name', '') or '',
            'email': getattr(request.user, 'email', '') or '',
            'contact': normalize_indian_phone(user_phone)
        }
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='verify')
    def verify(self, request, pk=None):
        purchase = get_object_or_404(CreditPurchase, pk=pk)
        academy = getattr(request.user, 'academy', None)
        if academy and purchase.academy_id != academy.id and not getattr(request.user, 'is_staff', False):
            raise PermissionDenied("Access denied to credit purchase order.")

        razorpay_payment_id = (request.data.get('razorpay_payment_id') or '').strip()
        razorpay_order_id = (request.data.get('razorpay_order_id') or '').strip()
        razorpay_signature = (request.data.get('razorpay_signature') or '').strip()

        if not razorpay_payment_id or not razorpay_order_id or not razorpay_signature:
            raise ValidationError({"detail": "Razorpay payment verification data is incomplete."})

        if purchase.payment_order_id != razorpay_order_id:
            raise ValidationError({"detail": "Payment order does not match this purchase."})

        from payments.services import PaymentGatewayService
        verify_res = PaymentGatewayService.verify_payment('RAZORPAY', {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature,
        })

        if not verify_res.get('is_success'):
            raise ValidationError({"detail": "Payment signature verification failed."})

        fulfilled_purchase, already_processed = CreditPurchaseService.finalize_credit_purchase(
            payment_order_id=purchase.payment_order_id,
            transaction_id=razorpay_payment_id,
            razorpay_order_id=razorpay_order_id,
            source="frontend_verify"
        )

        current_balance = CreditsService.get_balance(purchase.academy)

        return Response({
            "success": True,
            "already_processed": already_processed,
            "message": "Payment verified and credits added successfully." if not already_processed else "Payment already processed.",
            "purchase_id": str(fulfilled_purchase.id),
            "payment_status": "SUCCESS",
            "credits_added": str(fulfilled_purchase.total_credits),
            "wallet_balance": str(current_balance),
            "purchase": CreditPurchaseSerializer(fulfilled_purchase).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='fulfill')
    def fulfill(self, request, pk=None):
        purchase = get_object_or_404(CreditPurchase, pk=pk)
        academy = getattr(request.user, 'academy', None)
        if academy and purchase.academy_id != academy.id and not getattr(request.user, 'is_staff', False):
            raise PermissionDenied("Access denied to credit purchase order.")

        serializer = FulfillPurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        fulfilled_purchase = CreditPurchaseService.fulfill_purchase(
            payment_order_id=purchase.payment_order_id,
            transaction_id=serializer.validated_data.get('payment_transaction_id', '')
        )

        return Response({
            "message": "Credit purchase fulfilled and wallet credited successfully.",
            "purchase": CreditPurchaseSerializer(fulfilled_purchase).data
        }, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 2. Super Admin Control Panel Endpoints
# --------------------------------------------------------------

class AdminCreditAccountsViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CreditAccountSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return CreditSelector.get_admin_all_accounts(
            status=self.request.query_params.get('status'),
            search=self.request.query_params.get('search')
        )

    @action(detail=True, methods=['post'], url_path='adjust')
    def adjust(self, request, pk=None):
        account = self.get_object()
        serializer = ManualAdjustmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        adjustment = CreditsService.adjust(
            academy=account.academy,
            amount=serializer.validated_data['amount'],
            adjustment_type=serializer.validated_data['adjustment_type'],
            reason=serializer.validated_data['reason'],
            requested_by=request.user,
            approved_by=request.user
        )

        return Response(CreditAdjustmentSerializer(adjustment).data, status=status.HTTP_200_OK)

class AdminCreditRateViewSet(viewsets.ModelViewSet):
    queryset = CreditRate.objects.all().order_by('feature_key')
    serializer_class = CreditRateSerializer
    permission_classes = [permissions.IsAdminUser]

class AdminCreditPackageViewSet(viewsets.ModelViewSet):
    queryset = CreditPackage.objects.all().order_by('sort_order', 'price')
    serializer_class = CreditPackageSerializer
    permission_classes = [permissions.IsAdminUser]

class AdminCreditCouponViewSet(viewsets.ModelViewSet):
    queryset = CreditPurchaseCoupon.objects.all().order_by('-created_at')
    serializer_class = CreditPurchaseCouponSerializer
    permission_classes = [permissions.IsAdminUser]

class AdminReversalView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, entry_id):
        serializer = ReversalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        compensating_entry = CreditsService.reverse_entry(
            entry_id=str(entry_id),
            reason=serializer.validated_data['reason'],
            performed_by=request.user
        )

        return Response({
            "message": "Ledger entry reversed successfully via compensating entry.",
            "compensating_entry": CreditLedgerEntrySerializer(compensating_entry).data
        }, status=status.HTTP_200_OK)
