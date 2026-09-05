import logging
from celery import shared_task
from django.utils import timezone
from academy.models import Academy

logger = logging.getLogger(__name__)

@shared_task(name='credits.create_daily_storage_snapshots')
def create_daily_storage_snapshots_task(date_str: str = None):
    """
    Daily snapshot task scheduled via Celery Beat at 00:05 daily (Section G).
    """
    from credits.services import StorageBillingService
    today = timezone.now().date()
    if date_str:
        try:
            today = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    snapshots = StorageBillingService.take_daily_snapshot(today)
    logger.info(f"Created {len(snapshots)} daily storage snapshots for date {today}.")
    return len(snapshots)


@shared_task(name='credits.process_monthly_billing')
def process_monthly_billing_task(year: int = None, month: int = None):
    """
    Monthly billing task scheduled via Celery Beat on 1st of month at 00:15 (Section Q).
    Runs atomically & idempotently for all academies.
    """
    from credits.services import MonthlyBillingService
    now = timezone.now()
    if not year or not month:
        # Default to previous calendar month
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_end = first_of_this_month - timezone.timedelta(seconds=1)
        period_start = prev_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end = prev_month_end
    else:
        period_start = timezone.datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
        if month == 12:
            period_end = timezone.datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc) - timezone.timedelta(seconds=1)
        else:
            period_end = timezone.datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc) - timezone.timedelta(seconds=1)

    invoices_generated = 0
    for academy in Academy.objects.all():
        try:
            invoice = MonthlyBillingService.generate_monthly_invoice(academy, period_start, period_end)
            if invoice:
                invoices_generated += 1
        except Exception as e:
            logger.error(f"Failed to generate monthly invoice for academy {academy.id}: {e}")

    logger.info(f"Processed monthly billing: {invoices_generated} invoices generated for period {period_start.strftime('%Y-%m')}.")
    return invoices_generated
