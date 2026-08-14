from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied

from academy.models import Academy
from credits.models import CreditAccount, CreditLedgerEntry
from credits.selectors import CreditSelector
from credits.services import CreditsService
from credits.serializers import (
    CreditAccountSerializer,
    CreditLedgerEntrySerializer,
    CreditAdjustmentSerializer,
    ManualAdjustmentRequestSerializer,
    ReversalRequestSerializer,
)

# --------------------------------------------------------------
# 1. Staff Credit Wallet Endpoints
# Access restricted to authenticated Academy Staff for their own Academy context.
# Academy tenant isolation is strictly enforced by deriving Academy from request.user.
# --------------------------------------------------------------

class CreditBalanceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Academy tenant isolation is enforced by deriving the Academy from authenticated request context.
        academy = getattr(request.user, 'academy', None)
        if not academy and not getattr(request.user, 'is_staff', False):
            raise ValidationError("User must belong to an Academy to access credit balance.")

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
            raise ValidationError("User must belong to an Academy to access credit summary.")

        summary_data = CreditSelector.get_academy_summary(academy)
        return Response(summary_data, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 2. Super Admin Credit Management ViewSet
# Platform-wide visibility and administrative adjustments for Super Admin roles.
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

    @action(detail=True, methods=['get'], url_path='ledger')
    def academy_ledger(self, request, pk=None):
        account = self.get_object()
        queryset = CreditSelector.get_academy_ledger(
            academy=account.academy,
            entry_type=request.query_params.get('entry_type'),
            source_type=request.query_params.get('source_type')
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = CreditLedgerEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = CreditLedgerEntrySerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
