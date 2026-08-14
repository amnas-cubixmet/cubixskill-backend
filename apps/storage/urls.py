#--------------------------------------------------------------
# Imports
#--------------------------------------------------------------

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from storage.views import RequestUploadUrlView, DirectUploadView, ConfirmUploadView, MediaFileViewSet, StorageUsageView

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'files', MediaFileViewSet, basename='storage-file')

urlpatterns = [
    path('upload-url/', RequestUploadUrlView.as_view(), name='storage-upload-url'),
    path('upload/', DirectUploadView.as_view(), name='storage-direct-upload'),
    path('uploads/<uuid:upload_id>/confirm/', ConfirmUploadView.as_view(), name='storage-upload-confirm'),
    path('usage/', StorageUsageView.as_view(), name='storage-usage'),
    path('', include(router.urls)),
]
