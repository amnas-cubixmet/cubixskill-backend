from academy.models import Academy
from django.core.management.base import BaseCommand
from storage.metering import StorageBillingService, StorageMeteringService
from storage.models import BillingStatus, StorageMonthlyBilling


class Command(BaseCommand):
    help = 'Storage metering operations: initialize baselines, build rollups, close billing periods, and charge billing.'

    def add_arguments(self, parser):
        parser.add_argument('--action', type=str, choices=['baseline', 'rollups', 'close_period', 'charge', 'reconcile'], default='close_period', help='Action to perform')
        parser.add_argument('--year', type=int, help='Year for billing period (e.g. 2026)')
        parser.add_argument('--month', type=int, help='Month for billing period (e.g. 8)')
        parser.add_argument('--academy_uuid', type=str, help='Specific Academy UUID')

    def handle(self, *args, **options):
        action = options.get('action')
        academy_uuid = options.get('academy_uuid')
        year = options.get('year')
        month = options.get('month')

        academies = Academy.objects.all()
        if academy_uuid:
            academies = academies.filter(id=academy_uuid)

        self.stdout.write(self.style.SUCCESS(f"Running storage metering command action: '{action}'..."))

        if action == 'baseline':
            for acad in academies:
                event = StorageMeteringService.initialize_baseline(acad.id)
                if event:
                    self.stdout.write(f"Initialized baseline for Academy '{acad.name}' ({acad.id}): {event.delta_bytes} bytes")
                else:
                    self.stdout.write(f"Academy '{acad.name}' baseline already initialized or skipped.")

        elif action == 'rollups':
            for acad in academies:
                rollup = StorageBillingService.build_daily_rollup(acad.id)
                self.stdout.write(f"Built daily rollup for Academy '{acad.name}': {rollup.byte_seconds} byte-seconds")

        elif action == 'close_period':
            for acad in academies:
                record = StorageBillingService.close_billing_period(acad.id, year=year, month=month)
                self.stdout.write(f"Closed billing period '{record.billing_period}' for Academy '{acad.name}': {record.billable_units_gb_month} GB-month ({record.credits_calculated} Credits)")

        elif action == 'charge':
            pending_records = StorageMonthlyBilling.objects.filter(
                status__in=[BillingStatus.CALCULATED, BillingStatus.INSUFFICIENT_CREDITS, BillingStatus.FAILED]
            )
            if academy_uuid:
                pending_records = pending_records.filter(academy_uuid=academy_uuid)

            for rec in pending_records:
                updated = StorageBillingService.charge_billing_period(rec)
                self.stdout.write(f"Charge attempt for billing record '{rec.id}' status: {updated.status}")

        elif action == 'reconcile':
            for acad in academies:
                mismatch = StorageBillingService.reconcile_academy_storage(acad.id)
                if mismatch:
                    self.stdout.write(self.style.WARNING(f"Reconciled storage mismatch for Academy '{acad.name}' ({acad.id})"))
                else:
                    self.stdout.write(f"Academy '{acad.name}' storage consistent.")

        self.stdout.write(self.style.SUCCESS("Storage metering command completed."))
