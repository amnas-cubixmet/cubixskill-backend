from decimal import Decimal
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied

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

class CreditPackageListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        packages = CreditPackageService.list_active_packages()
        serializer = CreditPackageSerializer(packages, many=True)
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
        package_id = serializer.validated_data['package_id']
        coupon_code = serializer.validated_data.get('coupon_code', '')

        try:
            package = CreditPackage.objects.get(pk=package_id, is_active=True)
        except CreditPackage.DoesNotExist:
            raise ValidationError({"package_id": "Selected credit package not found."})

        discount_amount = Decimal('0.00')
        coupon_obj = None
        if coupon_code and coupon_code.strip():
            coupon_obj, discount_amount = CreditCouponService.validate_coupon(coupon_code, package.price, academy)

        final_price = max(package.price - discount_amount, Decimal('0.00'))

        return Response({
            "valid": True,
            "package_id": str(package.id),
            "coupon_code": coupon_obj.code if coupon_obj else "",
            "description": coupon_obj.description if coupon_obj else "",
            "discount_type": coupon_obj.discount_type if coupon_obj else "",
            "discount_value": str(coupon_obj.discount_value) if coupon_obj else "0.00",
            "original_price": str(package.price),
            "discount_amount": str(discount_amount),
            "final_price": str(final_price),
            "credits": str(package.credits),
            "bonus_credits": str(package.bonus_credits),
            "total_credits": str(package.credits + package.bonus_credits),
            "currency": package.currency,
        })

    @action(detail=False, methods=['post'], url_path='create-order')
    def create_order(self, request):
        serializer = CreatePurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        academy = getattr(request.user, 'academy', None)
        if not academy:
            academy = CreditsService.get_or_create_account(None).academy

        purchase, checkout_url = CreditPurchaseService.create_purchase_order(
            academy=academy,
            package_id=str(serializer.validated_data['package_id']),
            coupon_code=serializer.validated_data.get('coupon_code', ''),
            user=request.user
        )

        data = CreditPurchaseSerializer(purchase).data
        data['checkout_url'] = checkout_url
        return Response(data, status=status.HTTP_201_CREATED)

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
