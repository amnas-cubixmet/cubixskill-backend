from credits.models import CreditAccount, CreditAdjustment, CreditLedgerEntry
from django.contrib import admin

# --------------------------------------------------------------
# Credits Admin Registration
# --------------------------------------------------------------

@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    list_display = ['academy', 'balance', 'currency_unit', 'total_credited', 'total_debited', 'status', 'last_transaction_at']
    list_filter = ['status']
    search_fields = ['academy__name', 'academy__slug']
    readonly_fields = ['balance', 'total_credited', 'total_debited', 'last_transaction_at']

@admin.register(CreditLedgerEntry)
class CreditLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ['id', 'account', 'entry_type', 'source_type', 'amount', 'balance_before', 'balance_after', 'idempotency_key', 'occurred_at']
    list_filter = ['entry_type', 'source_type', 'occurred_at']
    search_fields = ['account__academy__name', 'idempotency_key', 'description', 'reference_id']
    readonly_fields = ['account', 'entry_type', 'source_type', 'amount', 'balance_before', 'balance_after', 'idempotency_key', 'occurred_at']

@admin.register(CreditAdjustment)
class CreditAdjustmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'account', 'adjustment_type', 'amount', 'status', 'requested_by', 'approved_by', 'created_at']
    list_filter = ['adjustment_type', 'status']
    search_fields = ['account__academy__name', 'reason']
