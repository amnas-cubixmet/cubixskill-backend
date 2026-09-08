from django.urls import include, path
from notifications.views import (
    EmailProviderWebhookView,
    NotificationPreferenceView,
    NotificationViewSet,
)
from rest_framework.routers import DefaultRouter

# --------------------------------------------------------------
# Notifications URL Router Configuration
# Centralized REST endpoints for in-app notifications, preferences,
# and provider delivery webhooks.
# --------------------------------------------------------------

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('notification-preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'),
    path('notifications/email/webhooks/<str:provider>/', EmailProviderWebhookView.as_view(), name='notification-email-webhook'),
    path('', include(router.urls)),
]
