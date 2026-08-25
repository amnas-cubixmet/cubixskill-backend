from django.urls import path, include
from rest_framework.routers import DefaultRouter
from payments.views import (
    AcademyPaymentSettingsView,
    VerifyAcademyRazorpayView,
    DisconnectAcademyRazorpayView,
    AcademySettlementsViewSet,
    CreatePaymentOrderView,
    VerifyPaymentSignatureView,
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
    CourseCouponListCreateView,
    CourseCouponDetailView,
    CourseCouponToggleView,
    CourseCouponRedemptionsView,
    CourseCouponGenerateCodeView,
)
from fees.views import (
    CourseFeeSummaryView,
    CourseDefaultFeePlanView,
    StudentFeeAccountListCreateView,
    StudentFeeAccountDetailView,
    CollectFeePaymentView,
    WaiveFeeView,
    SendFeeReminderView,
    CourseFeePaymentsLedgerView,
)

# --------------------------------------------------------------
# Payments URL Router Configuration
# Centralized REST endpoints for dual payment architecture, checkouts, coupons, webhooks, and settlements.
# --------------------------------------------------------------

router = DefaultRouter()
router.register(r'student/payments', StudentPaymentHistoryViewSet, basename='student-payments')
router.register(r'academy/payments', AcademyPaymentHistoryViewSet, basename='academy-payments')
router.register(r'admin/payments', AdminPaymentHistoryViewSet, basename='admin-payments')
router.register(r'academy/coupons', AcademyCouponViewSet, basename='academy-coupons')
router.register(r'admin/platform-coupons', AdminPlatformCouponViewSet, basename='admin-platform-coupons')
router.register(r'settlements', AcademySettlementsViewSet, basename='academy-settlements')

urlpatterns = [
    # Dual Payment Settings & Credentials APIs
    path('settings/', AcademyPaymentSettingsView.as_view(), name='payment-settings'),
    path('settings/verify-razorpay/', VerifyAcademyRazorpayView.as_view(), name='verify-razorpay'),
    path('settings/academy-razorpay/', DisconnectAcademyRazorpayView.as_view(), name='disconnect-razorpay'),

    # Order Creation & Signature Verification APIs
    path('orders/', CreatePaymentOrderView.as_view(), name='create-payment-order'),
    path('verify/', VerifyPaymentSignatureView.as_view(), name='verify-payment-signature'),

    # Webhook Endpoints
    path('razorpay/webhook/', PaymentWebhookView.as_view(), {'gateway': 'razorpay'}, name='razorpay-webhook-direct'),
    path('webhooks/razorpay/', PaymentWebhookView.as_view(), {'gateway': 'razorpay'}, name='razorpay-webhook-central'),
    path('webhooks/razorpay/academy/<uuid:academy_uuid>/', PaymentWebhookView.as_view(), {'gateway': 'razorpay'}, name='razorpay-webhook-academy'),
    path('webhooks/<str:gateway>/', PaymentWebhookView.as_view(), name='payment-webhook'),

    # Existing Checkout & Coupon Routes
    path('courses/<uuid:course_id>/checkout/', CourseCheckoutView.as_view(), name='course-checkout'),
    path('payment-orders/<uuid:order_id>/pay/', PayOrderView.as_view(), name='pay-order'),
    path('coupons/validate/', ValidateCouponView.as_view(), name='validate-coupon'),
    path('platform/checkout/', PlatformCheckoutView.as_view(), name='platform-checkout'),

    # Course Coupon Routes
    path('courses/<uuid:course_id>/coupons/', CourseCouponListCreateView.as_view(), name='course-coupons'),
    path('courses/<uuid:course_id>/coupons/generate-code/', CourseCouponGenerateCodeView.as_view(), name='course-coupons-generate-code'),
    path('courses/<uuid:course_id>/coupons/validate/', ValidateCouponView.as_view(), name='course-coupons-validate'),
    path('courses/<uuid:course_id>/coupons/<uuid:coupon_id>/', CourseCouponDetailView.as_view(), name='course-coupon-detail'),
    path('courses/<uuid:course_id>/coupons/<uuid:coupon_id>/deactivate/', CourseCouponToggleView.as_view(), name='course-coupon-deactivate'),
    path('courses/<uuid:course_id>/coupons/<uuid:coupon_id>/redemptions/', CourseCouponRedemptionsView.as_view(), name='course-coupon-redemptions'),

    # Fee Collection Routes
    path('courses/<uuid:course_id>/fee-summary/', CourseFeeSummaryView.as_view(), name='course-fee-summary'),
    path('courses/<uuid:course_id>/fee-configuration/', CourseDefaultFeePlanView.as_view(), name='course-fee-configuration'),
    path('courses/<uuid:course_id>/fee-accounts/', StudentFeeAccountListCreateView.as_view(), name='course-fee-accounts'),
    path('courses/<uuid:course_id>/fee-accounts/<uuid:account_id>/', StudentFeeAccountDetailView.as_view(), name='student-fee-account-detail'),
    path('courses/<uuid:course_id>/fee-accounts/<uuid:account_id>/payments/', CollectFeePaymentView.as_view(), name='collect-fee-payment'),
    path('courses/<uuid:course_id>/fee-accounts/<uuid:account_id>/waive/', WaiveFeeView.as_view(), name='waive-fee'),
    path('courses/<uuid:course_id>/fee-accounts/<uuid:account_id>/reminder/', SendFeeReminderView.as_view(), name='send-fee-reminder'),
    path('courses/<uuid:course_id>/fee-payments/', CourseFeePaymentsLedgerView.as_view(), name='course-fee-payments-ledger'),

    path('', include(router.urls)),
]
