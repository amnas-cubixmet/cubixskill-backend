#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from storage.views import (
    ConfirmUploadView,
    ControlPanelStorageSettingsView,
    DirectUploadView,
    EstimateUploadCostView,
    MediaFileViewSet,
    RequestUploadUrlView,
    StorageBillingPeriodsView,
    StorageCurrentPeriodView,
    StorageDailyRollupView,
    StorageMeterLogsView,
    StorageMeterFileInventoryView,
    StorageMonthlyBillingView,
    StorageSettlementHistoryView,
    StorageSnapshotsView,
    StorageSummaryDashboardView,
    StorageUsageView,
)

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'files', MediaFileViewSet, basename='storage-file')

urlpatterns = [
    path('summary/', StorageSummaryDashboardView.as_view(), name='storage-summary-dashboard'),
    path('meter-logs/', StorageMeterLogsView.as_view(), name='storage-meter-logs'),
    path('meter-logs/<uuid:meter_id>/files/', StorageMeterFileInventoryView.as_view(), name='storage-meter-files'),
    path('settlements/', StorageSettlementHistoryView.as_view(), name='storage-settlements'),
    path('snapshots/', StorageSnapshotsView.as_view(), name='storage-snapshots'),
    path('billing-periods/', StorageBillingPeriodsView.as_view(), name='storage-billing-periods'),
    path('control-panel/settings/', ControlPanelStorageSettingsView.as_view(), name='storage-cp-settings'),

    path('estimate/', EstimateUploadCostView.as_view(), name='storage-estimate'),
    path('estimate-upload/', EstimateUploadCostView.as_view(), name='storage-estimate-upload'),
    path('upload-url/', RequestUploadUrlView.as_view(), name='storage-upload-url'),
    path('upload/', DirectUploadView.as_view(), name='storage-direct-upload'),
    path('uploads/<uuid:upload_id>/confirm/', ConfirmUploadView.as_view(), name='storage-upload-confirm'),
    path('usage/', StorageUsageView.as_view(), name='storage-usage'),
    path('usage/current-period/', StorageCurrentPeriodView.as_view(), name='storage-current-period'),
    path('usage/daily/', StorageDailyRollupView.as_view(), name='storage-daily-rollups'),
    path('billing/', StorageMonthlyBillingView.as_view(), name='storage-monthly-billings'),
    path('', include(router.urls)),
]

