from django.urls import path, include
from rest_framework.routers import DefaultRouter
from payments.views import (
    CourseCheckoutView,
    PayOrderView,
    ValidateCouponView,
    PlatformCheckoutView,
    PaymentWebhookView,
    StudentPaymentHistoryViewSet,
    AcademyPaymentHistoryViewSet,
    AdminPaymentHistoryViewSet,
    AcademyCouponViewSet,
    AdminPlatformCouponViewSet,
)

# --------------------------------------------------------------
# Payments URL Router Configuration
# Centralized REST endpoints for checkouts, coupons, webhooks, and payment history.
# --------------------------------------------------------------

router = DefaultRouter()
router.register(r'student/payments', StudentPaymentHistoryViewSet, basename='student-payments')
router.register(r'academy/payments', AcademyPaymentHistoryViewSet, basename='academy-payments')
router.register(r'admin/payments', AdminPaymentHistoryViewSet, basename='admin-payments')
router.register(r'academy/coupons', AcademyCouponViewSet, basename='academy-coupons')
router.register(r'admin/platform-coupons', AdminPlatformCouponViewSet, basename='admin-platform-coupons')

urlpatterns = [
    path('courses/<uuid:course_id>/checkout/', CourseCheckoutView.as_view(), name='course-checkout'),
    path('payment-orders/<uuid:order_id>/pay/', PayOrderView.as_view(), name='pay-order'),
    path('coupons/validate/', ValidateCouponView.as_view(), name='validate-coupon'),
    path('platform/checkout/', PlatformCheckoutView.as_view(), name='platform-checkout'),
    path('payments/webhooks/<str:gateway>/', PaymentWebhookView.as_view(), name='payment-webhook'),
    path('', include(router.urls)),
]
