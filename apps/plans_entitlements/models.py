from django.db import models
from core.models import BaseModel, ActiveMixin

class Plan(BaseModel, ActiveMixin):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, default='')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    credits = models.BigIntegerField(default=10000)

    class Meta:
        db_table = 'plans'

class PlanFeature(BaseModel):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='plan_features', null=True, blank=True)
    feature = models.ForeignKey('features.Feature', on_delete=models.CASCADE, null=True, blank=True)
    limit_value = models.IntegerField(default=-1)  # -1 = unlimited

    class Meta:
        db_table = 'plan_features'
        unique_together = ('plan', 'feature')

class AcademySubscription(BaseModel, ActiveMixin):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='subscriptions', null=True, blank=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions', null=True, blank=True)

    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_auto_renew = models.BooleanField(default=True)

    class Meta:
        db_table = 'academy_subscriptions'

class AcademyFeatureOverride(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='feature_overrides', null=True, blank=True)
    feature = models.ForeignKey('features.Feature', on_delete=models.CASCADE, null=True, blank=True)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'academy_feature_overrides'
        unique_together = ('academy', 'feature')

class AddOn(BaseModel, ActiveMixin):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'add_ons'

class AcademyAddOn(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, related_name='add_ons', null=True, blank=True)
    add_on = models.ForeignKey(AddOn, on_delete=models.CASCADE, null=True, blank=True)
    activated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'academy_add_ons'
