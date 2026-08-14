import os
import sys
from pathlib import Path

# --------------------------------------------------------------
# System Path Setup
# Adds apps directory to sys.path before loading Django modules.
# --------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
APPS_DIR = BASE_DIR / 'apps'
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
try:
    from discussions_chat.middleware import TokenAuthMiddleware
    import discussions_chat.routing as chat_routing
except ImportError:
    from apps.discussions_chat.middleware import TokenAuthMiddleware
    import apps.discussions_chat.routing as chat_routing

# --------------------------------------------------------------
# ASGI Application Router
# Directs HTTP traffic to Django ASGI and WebSocket traffic to Channels.
# --------------------------------------------------------------

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': TokenAuthMiddleware(
        URLRouter(
            chat_routing.websocket_urlpatterns
        )
    ),
})
