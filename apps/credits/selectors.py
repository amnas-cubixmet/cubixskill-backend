from decimal import Decimal
from django.db.models import QuerySet, Sum, Q
from django.utils import timezone
from credits.models import (
    CreditAccount,
    CreditLedgerEntry,
    CreditRate,
    LedgerEntryType,
    CreditSourceType,
)

from credits.services import CreditsService

LOW_BALANCE_THRESHOLD = Decimal('100.000000')

class CreditSelector:

    @classmethod
    def get_account_balance(cls, academy) -> dict:
        """
        Retrieves current wallet balance and metrics for an Academy.
        """
        account = CreditsService.get_or_create_account(academy)
        is_low = account.balance < LOW_BALANCE_THRESHOLD
        return {
            'balance': str(account.balance),
            'currency_unit': account.currency_unit,
            'total_credited': str(account.total_credited),
            'total_debited': str(account.total_debited),
            'status': account.status,
            'is_low_balance': is_low,
            'low_balance_threshold': str(LOW_BALANCE_THRESHOLD),
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

        if entry_type and entry_type != 'all':
            queryset = queryset.filter(entry_type=entry_type.upper())
        if source_type and source_type != 'all':
            queryset = queryset.filter(source_type=source_type.upper())
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
        account = CreditsService.get_or_create_account(academy)
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

        email_usage_this_month = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.DEBIT,
            source_type=CreditSourceType.EMAIL_USAGE,
            occurred_at__gte=month_start
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.000000')

        is_low = account.balance < LOW_BALANCE_THRESHOLD

        rates = {
            r.feature_key: {
                'name': r.name,
                'billing_type': r.billing_type,
                'unit_size': str(r.unit_size),
                'credit_cost': str(r.credit_cost),
            }
            for r in CreditRate.objects.filter(is_active=True)
        }

        return {
            'balance': str(account.balance),
            'available_credits': str(account.balance),
            'currency_unit': account.currency_unit,
            'total_credited': str(account.total_credited),
            'lifetime_credited': str(account.total_credited),
            'total_debited': str(account.total_debited),
            'lifetime_debited': str(account.total_debited),
            'credited_this_month': str(credited_this_month),
            'debited_this_month': str(debited_this_month),
            'used_this_month': str(debited_this_month),
            'storage_usage_credits_this_month': str(storage_usage_this_month),
            'email_usage_credits_this_month': str(email_usage_this_month),
            'is_low_balance': is_low,
            'low_balance_threshold': str(LOW_BALANCE_THRESHOLD),
            'rates': rates,
        }

    @classmethod
    def get_usage_breakdown(cls, academy) -> list[dict]:
        account = CreditsService.get_or_create_account(academy)
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        usage_qs = CreditLedgerEntry.objects.filter(
            account=account,
            entry_type=LedgerEntryType.DEBIT,
            occurred_at__gte=month_start
        ).values('source_type').annotate(total=Sum('amount')).order_by('-total')

        result = []
        for item in usage_qs:
            src = item['source_type']
            label = dict(CreditSourceType.choices).get(src, src)
            result.append({
                'source_type': src,
                'label': label,
                'credits_used': str(item['total'] or Decimal('0.000000'))
            })
        return result

    @classmethod
    def get_admin_all_accounts(cls, status: str = None, search: str = None) -> QuerySet[CreditAccount]:
        queryset = CreditAccount.objects.select_related('academy').order_by('-created_at')

        if status:
            queryset = queryset.filter(status=status)
        if search:
            queryset = queryset.filter(
                Q(academy__name__icontains=search) |
                Q(academy__slug__icontains=search)
            )

        return queryset
