from django.urls import re_path
from academy.consumers import AcademyEventsConsumer

websocket_urlpatterns = [
    re_path(r'^ws/academy-events/$', AcademyEventsConsumer.as_asgi()),
]
