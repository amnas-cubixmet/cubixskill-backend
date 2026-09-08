from academy.consumers import AcademyEventsConsumer
from django.urls import re_path

websocket_urlpatterns = [
    re_path(r'^ws/academy-events/$', AcademyEventsConsumer.as_asgi()),
]
