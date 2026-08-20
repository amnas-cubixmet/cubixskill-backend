from django.db import models
from core.models import BaseModel, ActiveMixin
from users_roles.models import User

# --------------------------------------------------------------
# 1. SystemSetting Model
# Key-value store for global platform settings.
# --------------------------------------------------------------

class SystemSetting(BaseModel):
    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.TextField(blank=True, default='')
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=50, default='GENERAL', db_index=True)  # GENERAL, ACADEMY_DEFAULTS, UPLOAD, BILLING, NOTIFICATIONS
    is_public = models.BooleanField(default=False)

    class Meta:
        db_table = 'control_system_settings'
        ordering = ['category', 'key']

    def __str__(self):
        return f"{self.key} = {self.value}"

# --------------------------------------------------------------
# 2. FeatureDefinition Model
# Central registry for global features and pricing defaults.
# --------------------------------------------------------------

class FeatureDefinition(BaseModel, ActiveMixin):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=50, default='GENERAL')
    
    enabled_globally = models.BooleanField(default=True)
    is_billable = models.BooleanField(default=False)
    
    base_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    billing_unit = models.CharField(max_length=50, blank=True, default='unit')  # student, GB, course, session, etc.
    included_quantity = models.IntegerField(default=0)  # -1 = unlimited
    overage_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'control_feature_definitions'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

# --------------------------------------------------------------
# 3. StorageBillingConfig Model
# Configurable storage billing engine settings.
# --------------------------------------------------------------

class StorageBillingConfig(BaseModel):
    storage_unit = models.CharField(max_length=10, default='GB')  # MB, GB, TB
    metering_interval_hours = models.IntegerField(default=12)  # 1, 2, 6, 12, 24, etc.
    price_per_unit = models.DecimalField(max_digits=12, decimal_places=4, default=0.50)  # Price in INR/Credits per unit per interval
    minimum_billable_usage = models.BigIntegerField(default=0)  # Bytes
    rounding_method = models.CharField(max_length=20, default='UP')  # UP, DOWN, EXACT
    billing_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'control_storage_billing_configs'

    def __str__(self):
        return f"Storage Billing: {self.price_per_unit} per {self.storage_unit}/{self.metering_interval_hours}h"

# --------------------------------------------------------------
# 4. UsageSnapshot Model
# Records periodic metric snapshots per academy.
# --------------------------------------------------------------

class UsageSnapshot(BaseModel):
    academy_uuid = models.UUIDField(db_index=True)
    metric = models.CharField(max_length=50, db_index=True)  # storage_mb, storage_gb, active_students, courses, etc.
    quantity = models.DecimalField(max_digits=20, decimal_places=4, default=0.00)
    unit = models.CharField(max_length=20, default='unit')
    recorded_at = models.DateTimeField(db_index=True)
    billing_cycle = models.CharField(max_length=50, blank=True, default='')
    charge_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    pricing_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'control_usage_snapshots'
        ordering = ['-recorded_at']

    def __str__(self):
        return f"Usage: {self.academy_uuid} - {self.metric}: {self.quantity} {self.unit}"
