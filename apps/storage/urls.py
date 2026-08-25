#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from storage.views import (
    RequestUploadUrlView, DirectUploadView, ConfirmUploadView, MediaFileViewSet,
    StorageUsageView, EstimateUploadCostView, StorageCurrentPeriodView,
    StorageDailyRollupView, StorageMonthlyBillingView
)

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'files', MediaFileViewSet, basename='storage-file')

urlpatterns = [
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
