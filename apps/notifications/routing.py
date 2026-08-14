from django.urls import re_path
from notifications.consumers import NotificationConsumer

# --------------------------------------------------------------
# WebSocket URL Routing for Notifications
# Centralized WebSocket route for real-time in-app notifications.
# --------------------------------------------------------------

websocket_urlpatterns = [
    re_path(r'^ws/notifications/$', NotificationConsumer.as_asgi()),
]
