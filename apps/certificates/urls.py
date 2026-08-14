from django.urls import path, include
from rest_framework.routers import DefaultRouter
from certificates.views import (
    PublicCertificateVerifyView,
    StudentCertificateViewSet,
    CertificateTemplateViewSet,
    CertificateViewSet,
    CertificateSettingsView,
)

router = DefaultRouter()
router.register(r'certificate-templates', CertificateTemplateViewSet, basename='certificate-template')
router.register(r'certificates', CertificateViewSet, basename='certificate')
router.register(r'student/certificates', StudentCertificateViewSet, basename='student-certificate')

urlpatterns = [
    path('certificates/verify/<str:verification_code>/', PublicCertificateVerifyView.as_view(), name='public-certificate-verify'),
    path('certificate-settings/', CertificateSettingsView.as_view(), name='certificate-settings'),
    path('', include(router.urls)),
]
