# CubixSkill storage billing security patch

## What is billed

The existing scheduled storage engine stores **Credits per GB per metering interval**,
not credits per GB-month. For example, 1 GB at 2 credits/GB/read and a 12-hour
interval accumulates approximately 4 credits per full day. These credits
accumulate in one OPEN academy billing cycle; **monthly settlement** debits
the wallet. Do not advertise this as 2 credits per GB-month. Use the
admin storage pricing form to set an appropriate per-interval amount.

The 10-second interval is development testing only and is rejected by the
platform settings API/form and metering task in production (`DEBUG=False`).
Do not enable continuous metering on real wallets until rates and cadence
have been reviewed.

### Storage sources

When an academy has any MediaFile records, the current stored usage is the
sum of **ACTIVE** MediaFile source and streaming bytes. Deleted files are
excluded on subsequent readings. Historical file snapshots remain. Older
installations with no registered MediaFiles keep their existing AcademyStorageUsage
counter as a backwards-compatible fallback. Reconcile storage separately if
external physical files are not represented by either source.

### Billing safety

- Only platform SUPER_ADMIN/SUPER_ADMIN_STAFF can modify pricing via
  `/api/v1/storage/control-panel/settings/`.
- Booleans are parsed by DRF, so `"false"` disables instead of enabling.
- Negative/invalid per-GB rates and unsupported intervals are rejected.
- Periodic metering locks the academy usage row and rechecks the due time to
  prevent simultaneous worker runs from creating duplicate snapshots.
- The legacy GB-month charge method and new interval-cycle settlement method
  reject overlapping periods already charged through the other engine.
- The wallet ledger remains authoritative. This patch does not fake credits.
- Existing alternate pricing/cost-estimation screens may still describe a
  different storage rate and should be audited before publishing pricing.

### Local tests

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test storage.test_settings_security storage.test_settlement_audit control_panel.tests --noinput
```

GitHub Actions runs these tests against a fresh PostgreSQL service.
Do not rely on the workflow alone as proof of production payment behavior.

### Deployment caution

Before enabling billing, verify Celery Beat and workers are running only
the intended metering and monthly settlement schedule. Reconcile active file
bytes, legacy outstanding charges, historical credit ledger entries and each
academy's existing unpaid storage balance. Legacy GB-month manual charge
endpoints remain for history/administration but cannot bill an interval
that has already settled through the new engine.

Existing wallet balances and historical ledger transactions are not
modified by this code change.
