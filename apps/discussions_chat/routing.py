from discussions_chat.consumers import ChatConsumer, CommunityDiscussionsConsumer
from django.urls import re_path

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<room_id>[0-9a-f-]+)/$', ChatConsumer.as_asgi()),
    re_path(r'ws/discussions/community/$', CommunityDiscussionsConsumer.as_asgi()),
]
