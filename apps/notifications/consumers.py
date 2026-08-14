import logging
from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# WebSocket Real-Time Consumer
# Connects authenticated users to private group notifications.user.{user_uuid}.
# Broadcasts real-time events for multi-device synchronization.
# WebSocket delivery failures must not lose stored database notifications.
# --------------------------------------------------------------

class NotificationConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            logger.warning("Unauthenticated WebSocket notification connection attempt rejected.")
            await self.close(code=4001)
            return

        self.user = user
        self.group_name = f"notifications.user.{user.id}"

        # Join private user notification group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        logger.info(f"WebSocket notification channel connected for user {user.email}")

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def notification_message(self, event):
        """
        Receives broadcast event from channel layer and forwards to WebSocket client.
        """
        await self.send_json({
            'type': event.get('event_type', 'notification.created'),
            'data': event.get('data', {})
        })


def broadcast_notification_event(user_id: str, event_type: str, data: dict):
    """
    Helper function to broadcast real-time notification events to a user's WebSocket group.
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    group_name = f"notifications.user.{user_id}"
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'notification_message',
            'event_type': event_type,
            'data': data
        }
    )
