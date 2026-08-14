from decimal import Decimal
from django.db.models import QuerySet, Sum, Q
from django.utils import timezone
from credits.models import (
    CreditAccount,
    CreditLedgerEntry,
    LedgerEntryType,
    CreditSourceType,
)

# --------------------------------------------------------------
# Credit Selectors
# Optimized Academy-scoped queries for credit balances, ledger histories,
# and summary analytics.
# --------------------------------------------------------------

class CreditSelector:

    @classmethod
    def get_account_balance(cls, academy) -> dict:
        """
        Retrieves current wallet balance and metrics for an Academy.
        """
        account, _ = CreditAccount.objects.get_or_create(academy=academy)
        return {
            'balance': str(account.balance),
            'currency_unit': account.currency_unit,
            'total_credited': str(account.total_credited),
            'total_debited': str(account.total_debited),
            'status': account.status,
            'last_transaction_at': account.last_transaction_at,
        }

    @classmethod
    def get_academy_ledger(
        cls,
        academy,
        entry_type: str = None,
        source_type: str = None,
        date_from=None,
        date_to=None
    ) -> QuerySet[CreditLedgerEntry]:
        """
        Retrieves paginated, filtered ledger entries for an Academy.
        """
        queryset = CreditLedgerEntry.objects.filter(
            account__academy=academy
        ).select_related('created_by')

        if entry_type:
            queryset = queryset.filter(entry_type=entry_type)
        if source_type:
            queryset = queryset.filter(source_type=source_type)
        if date_from:
            queryset = queryset.filter(occurred_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(occurred_at__lte=date_to)

        return queryset.order_by('-occurred_at')

    @classmethod
    def get_academy_summary(cls, academy) -> dict:
        """
        Calculates monthly credit usage and grant analytics for an Academy.
        """
        account, _ = CreditAccount.objects.get_or_create(academy=academy)
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        credited_this_month = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.CREDIT,
            occurred_at__gte=month_start
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.000000')

        debited_this_month = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.DEBIT,
            occurred_at__gte=month_start
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.000000')

        storage_usage_this_month = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.DEBIT,
            source_type=CreditSourceType.STORAGE_USAGE,
            occurred_at__gte=month_start
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.000000')

        return {
            'balance': str(account.balance),
            'currency_unit': account.currency_unit,
            'total_credited': str(account.total_credited),
            'total_debited': str(account.total_debited),
            'credited_this_month': str(credited_this_month),
            'debited_this_month': str(debited_this_month),
            'storage_usage_credits_this_month': str(storage_usage_this_month),
        }

    @classmethod
    def get_admin_all_accounts(cls, status: str = None, search: str = None) -> QuerySet[CreditAccount]:
        """
        Retrieves all Academy credit accounts for Super Admin visibility.
        """
        queryset = CreditAccount.objects.select_related('academy').order_by('-created_at')

        if status:
            queryset = queryset.filter(status=status)
        if search:
            queryset = queryset.filter(
                Q(academy__name__icontains=search) |
                Q(academy__slug__icontains=search)
            )

        return queryset
