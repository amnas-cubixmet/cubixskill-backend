from decimal import Decimal

from django import forms
from django.conf import settings
from storage.models import StorageBillingInterval, StorageBillingSettings


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
            "storage_credit_rate_per_gb": "Credits per GB per metering interval",
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

    def clean(self):
        result = super().clean()
        if (not settings.STORAGE_ALLOW_10_SECOND_METERING
                and result.get("storage_billing_enabled")
                and result.get("storage_billing_interval") == "10_SECONDS"):
            self.add_error(
                "storage_billing_interval",
                "10-second test metering is disabled in production.",
            )
        return result

    def clean_storage_credit_debit_day(self):
        day = self.cleaned_data.get("storage_credit_debit_day")
        if day is None or day < 1 or day > 31:
            raise forms.ValidationError("Settlement day must be between 1 and 31.")
        return day
