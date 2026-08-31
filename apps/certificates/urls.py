from django.urls import path, include
from rest_framework.routers import DefaultRouter
from certificates.views import (
    PublicCertificateVerifyView,
    CertificateTemplateBindingsView,
    StudentCertificateViewSet,
    CertificateTemplateViewSet,
    CertificateViewSet,
    CertificateSettingsView,
    CertificateFontViewSet,
)

router = DefaultRouter()
router.register(r'certificate-templates', CertificateTemplateViewSet, basename='certificate-template')
router.register(r'fonts', CertificateFontViewSet, basename='certificate-font')
router.register(r'certificates', CertificateViewSet, basename='certificate')
router.register(r'student/certificates', StudentCertificateViewSet, basename='student-certificate')

urlpatterns = [
    path('template-bindings/', CertificateTemplateBindingsView.as_view(), name='certificate-template-bindings'),
    path('certificates/verify/<str:verification_code>/', PublicCertificateVerifyView.as_view(), name='public-certificate-verify'),
    path('certificate-settings/', CertificateSettingsView.as_view(), name='certificate-settings'),
    path('', include(router.urls)),
]
