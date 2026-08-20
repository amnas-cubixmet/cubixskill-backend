#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from storage.views import RequestUploadUrlView, DirectUploadView, ConfirmUploadView, MediaFileViewSet, StorageUsageView, EstimateUploadCostView

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'files', MediaFileViewSet, basename='storage-file')

urlpatterns = [
    path('estimate/', EstimateUploadCostView.as_view(), name='storage-estimate'),
    path('upload-url/', RequestUploadUrlView.as_view(), name='storage-upload-url'),
    path('upload/', DirectUploadView.as_view(), name='storage-direct-upload'),
    path('uploads/<uuid:upload_id>/confirm/', ConfirmUploadView.as_view(), name='storage-upload-confirm'),
    path('usage/', StorageUsageView.as_view(), name='storage-usage'),
    path('', include(router.urls)),
]
