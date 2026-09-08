import calendar
import math
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

BYTES_PER_GB = Decimal(1024 ** 3)

def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def bytes_to_gb(bytes_num: int) -> Decimal:
    if not bytes_num or bytes_num <= 0:
        return Decimal("0.000000")
    return (Decimal(bytes_num) / BYTES_PER_GB).quantize(Decimal("0.000001"))

class InvalidStorageBillingInterval(Exception):
    pass

INTERVAL_LABELS = {
    "10_SECONDS": "10 Seconds â€” Test",
    "6_HOURS": "6 Hours",
    "12_HOURS": "12 Hours",
    "18_HOURS": "18 Hours",
    "1_DAY": "1 Day",
}

def storage_interval_delta(interval: str) -> timedelta:
    if interval == "10_SECONDS":
        return timedelta(seconds=10)
    if interval == "6_HOURS":
        return timedelta(hours=6)
    if interval == "12_HOURS":
        return timedelta(hours=12)
    if interval == "18_HOURS":
        return timedelta(hours=18)
    if interval == "1_DAY":
        return timedelta(days=1)
    raise InvalidStorageBillingInterval(f"Invalid storage billing interval: {interval}")

def get_interval_label(interval: str) -> str:
    return INTERVAL_LABELS.get(interval, interval)

def get_storage_debit_datetime(year: int, month: int, day: int, debit_time: time = None, tz=None) -> datetime:
    if debit_time is None:
        debit_time = time(0, 0)
    if tz is None:
        tz = timezone.get_current_timezone()
    
    # Clamp day to max valid days in month
    _, max_days = calendar.monthrange(year, month)
    valid_day = min(day, max_days)

    naive_dt = datetime(year, month, valid_day, debit_time.hour, debit_time.minute, debit_time.second)
    return timezone.make_aware(naive_dt, tz)

def get_next_credit_debit_datetime(settings_obj, now=None) -> datetime:
    if not now:
        now = timezone.localtime()
    day = getattr(settings_obj, 'storage_credit_debit_day', 1) or 1
    debit_time = getattr(settings_obj, 'storage_credit_debit_time', None) or time(0, 0)
    tz = timezone.get_current_timezone()

    target_dt = get_storage_debit_datetime(now.year, now.month, day, debit_time, tz)
    if now >= target_dt:
        if now.month == 12:
            next_year = now.year + 1
            next_month = 1
        else:
            next_year = now.year
            next_month = now.month + 1
        target_dt = get_storage_debit_datetime(next_year, next_month, day, debit_time, tz)
    return target_dt

def format_bytes(bytes_num: int) -> str:
    if not bytes_num or bytes_num <= 0:
        return '0 B'
    k = 1024
    sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    i = int(math.floor(math.log(bytes_num, k)))
    i = min(i, len(sizes) - 1)
    val = round(bytes_num / (k ** i), 1)
    if val == int(val):
        val = int(val)
    return f"{val} {sizes[i]}"

def repair_duplicate_open_storage_cycles():
    """
    Finds Academies with multiple OPEN StorageBillingCycles, moves all meter records into the canonical
    OPEN cycle, recalculates accumulated_credits from meter records, and deletes empty duplicate OPEN cycles.
    """
    from decimal import Decimal

    from academy.models import Academy
    from django.db import models
    from django.db.models import Count, Sum
    from storage.models import StorageBillingCycle, StorageBillingCycleStatus

    academies = Academy.objects.annotate(
        open_count=Count('storage_billing_cycles', filter=models.Q(storage_billing_cycles__status=StorageBillingCycleStatus.OPEN))
    ).filter(open_count__gt=1)

    for acad in academies:
        open_cycles = list(StorageBillingCycle.objects.filter(
            academy=acad,
            status=StorageBillingCycleStatus.OPEN
        ).order_by('cycle_start_at'))

        if not open_cycles:
            continue

        canonical = open_cycles[0]
        duplicates = open_cycles[1:]

        for dup in duplicates:
            dup.meter_records.update(billing_cycle=canonical)
            dup.delete()

        total = canonical.meter_records.aggregate(t=Sum('calculated_credits'))['t'] or Decimal("0.0000")
        canonical.accumulated_credits = total
        canonical.save(update_fields=['accumulated_credits'])

