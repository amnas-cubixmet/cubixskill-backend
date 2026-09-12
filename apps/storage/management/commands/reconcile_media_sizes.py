import os
from django.core.management.base import BaseCommand
from django.conf import settings
from storage.models import MediaFile, MediaStatus

class Command(BaseCommand):
    help = "Reconcile missing or suspicious 0-byte media file sizes from stored filesystem metadata."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report files that would be updated without saving changes to the database.',
        )
        parser.add_argument(
            '--academy',
            type=str,
            help='Filter reconciliation by specific Academy UUID.',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        academy_uuid = options.get('academy')

        qs = MediaFile.objects.exclude(status=MediaStatus.DELETED)
        if academy_uuid:
            qs = qs.filter(academy_uuid=academy_uuid)

        zero_files = qs.filter(size_bytes=0)
        self.stdout.write(f"Found {zero_files.count()} file(s) with size_bytes = 0.")

        reconciled_count = 0
        missing_count = 0

        for media in zero_files:
            if not media.storage_key:
                self.stdout.write(self.style.WARNING(f"File {media.id} ({media.original_filename}): No storage_key configured."))
                missing_count += 1
                continue

            local_path = os.path.join(settings.MEDIA_ROOT, media.storage_key)
            if os.path.exists(local_path) and os.path.isfile(local_path):
                actual_size = os.path.getsize(local_path)
                if actual_size > 0:
                    self.stdout.write(
                        self.style.SUCCESS(f"{'[DRY RUN] ' if dry_run else ''}Updated {media.id} ({media.original_filename}): 0 -> {actual_size} bytes")
                    )
                    reconciled_count += 1
                    if not dry_run:
                        media.size_bytes = actual_size
                        media.save(update_fields=['size_bytes'])
                else:
                    self.stdout.write(self.style.WARNING(f"File {media.id} ({media.original_filename}): File exists on disk but is genuinely 0 bytes."))
            else:
                self.stdout.write(self.style.ERROR(f"File {media.id} ({media.original_filename}): Object missing at disk path {local_path}."))
                missing_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nReconciliation finished: {reconciled_count} reconciled, {missing_count} missing/inaccessible."
            )
        )
