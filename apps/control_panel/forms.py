from django import forms
from decimal import Decimal
from storage.models import StorageBillingSettings, StorageBillingInterval

class StorageBillingSettingsForm(forms.ModelForm):
    class Meta:
        model = StorageBillingSettings
        fields = [
            "storage_billing_enabled",
            "storage_billing_interval",
            "storage_credit_rate_per_gb",
            "storage_credit_debit_day",
            "storage_credit_debit_time",
        ]
        labels = {
            "storage_billing_enabled": "Storage Billing",
            "storage_billing_interval": "Metering Interval",
            "storage_credit_rate_per_gb": "Credit Rate per GB",
            "storage_credit_debit_day": "Credit Settlement Day",
            "storage_credit_debit_time": "Credit Settlement Time",
        }

    def clean_storage_billing_interval(self):
        interval = self.cleaned_data.get("storage_billing_interval")
        if interval not in StorageBillingInterval.values:
            raise forms.ValidationError(f"Invalid metering interval '{interval}'. Allowed choices: 10_SECONDS, 6_HOURS, 12_HOURS, 18_HOURS, 1_DAY.")
        return interval

    def clean_storage_credit_rate_per_gb(self):
        rate = self.cleaned_data.get("storage_credit_rate_per_gb")
        if rate is None:
            raise forms.ValidationError("Credit rate per GB is required.")
        if rate < Decimal("0.0000"):
            raise forms.ValidationError("Credit rate must be greater than or equal to 0.")
        return rate

    def clean_storage_credit_debit_day(self):
        day = self.cleaned_data.get("storage_credit_debit_day")
        if day is None or day < 1 or day > 31:
            raise forms.ValidationError("Settlement day must be between 1 and 31.")
        return day
