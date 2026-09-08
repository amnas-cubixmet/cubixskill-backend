import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class AcademyEventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        academy_uuid = await self.get_user_academy_uuid(user)
        if not academy_uuid:
            await self.close(code=4003)
            return

        self.academy_uuid = str(academy_uuid)
        self.group_name = f"academy_events_{self.academy_uuid}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    @database_sync_to_async
    def get_user_academy_uuid(self, user):
        if hasattr(user, 'academy') and user.academy:
            return str(user.academy.id)
        if hasattr(user, 'academy_id') and user.academy_id:
            return str(user.academy_id)
        return None

    async def academy_event(self, event):
        data = event.get('data', {})
        await self.send_json(data)
