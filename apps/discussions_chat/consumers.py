import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

# --------------------------------------------------------------
# Realtime Chat Consumer
# Handles WebSocket connections, presence events, and real-time message broadcasting.
# PostgreSQL is the durable message source of truth.
# Redis is used only for realtime fan-out, presence, and typing state.
# --------------------------------------------------------------

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'
        self.user = self.scope.get('user')

        # 1. Authenticated User Check
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # 2. Strict Room Access & Feature Check
        is_allowed = await self.validate_access(self.user, self.room_id)
        if not is_allowed:
            await self.close(code=4003)
            return

        # 3. Join Channel Group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

        # 4. Broadcast participant joined
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_participant_event',
                'event_type': 'participant.joined',
                'user_id': str(self.user.id),
                'user_name': self.user.full_name or self.user.email
            }
        )

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_participant_event',
                    'event_type': 'participant.left',
                    'user_id': str(self.user.id) if self.user and self.user.is_authenticated else None
                }
            )
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        event_type = data.get('type')

        if event_type == 'message.send':
            client_request_id = data.get('client_request_id')
            content = data.get('content', '')
            message_type = data.get('message_type', 'TEXT')
            reply_to_id = data.get('reply_to_id')
            media_file_ids = data.get('media_file_ids', [])

            try:
                msg_data = await self.save_message(
                    self.user,
                    self.room_id,
                    content,
                    message_type=message_type,
                    reply_to_id=reply_to_id,
                    media_file_ids=media_file_ids
                )

                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message_created',
                        'message': msg_data,
                        'client_request_id': client_request_id
                    }
                )
            except Exception as exc:
                err_detail = getattr(exc, 'detail', str(exc))
                err_code = getattr(exc, 'code', 'SEND_ERROR')
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'request_type': 'message.send',
                    'client_request_id': client_request_id,
                    'code': err_code,
                    'detail': err_detail
                }, default=str))

        elif event_type in ['typing.start', 'typing.stop']:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_typing_status',
                    'event_type': event_type,
                    'user_id': str(self.user.id),
                    'user_name': self.user.full_name or self.user.email
                }
            )

        elif event_type in ['message.read', 'messages.read']:
            last_read_id = data.get('last_read_message_id')
            await self.mark_read(self.user, self.room_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message_read',
                    'user_id': str(self.user.id),
                    'last_read_message_id': last_read_id
                }
            )

    #--------------------------------------------------------------
    # Group Handlers
    #--------------------------------------------------------------

    async def chat_message_created(self, event):
        payload = {
            'type': 'message.created',
            'data': event['message']
        }
        if event.get('client_request_id'):
            payload['client_request_id'] = event['client_request_id']
        await self.send(text_data=json.dumps(payload, default=str))

    async def chat_typing_status(self, event):
        await self.send(text_data=json.dumps({
            'type': event['event_type'],
            'user_id': event['user_id'],
            'user_name': event['user_name']
        }, default=str))

    async def chat_message_read(self, event):
        payload = {
            'type': 'message.read',
            'user_id': event['user_id']
        }
        if event.get('last_read_message_id'):
            payload['last_read_message_id'] = event['last_read_message_id']
        await self.send(text_data=json.dumps(payload, default=str))

    async def chat_participant_event(self, event):
        await self.send(text_data=json.dumps({
            'type': event['event_type'],
            'user_id': event['user_id'],
            'user_name': event.get('user_name', '')
        }, default=str))

    #--------------------------------------------------------------
    # Database Helper Operations
    #--------------------------------------------------------------

    @database_sync_to_async
    def validate_access(self, user, room_id):
        from discussions_chat.models import ChatRoom
        from discussions_chat.services import ChatService
        try:
            room = ChatRoom.objects.get(id=room_id)
            return ChatService.validate_chat_access(user, room)
        except Exception:
            return False

    @database_sync_to_async
    def save_message(self, user, room_id, content, message_type='TEXT', reply_to_id=None, media_file_ids=None):
        from discussions_chat.models import ChatRoom
        from discussions_chat.services import ChatService
        from discussions_chat.serializers import ChatMessageSerializer

        room = ChatRoom.objects.get(id=room_id)
        msg = ChatService.send_message(
            room=room,
            user=user,
            content=content,
            message_type=message_type,
            reply_to_id=reply_to_id,
            media_file_ids=media_file_ids
        )
        return ChatMessageSerializer(msg).data

    @database_sync_to_async
    def mark_read(self, user, room_id):
        from discussions_chat.models import ChatRoom
        from discussions_chat.services import ChatService
        try:
            room = ChatRoom.objects.get(id=room_id)
            ChatService.mark_room_as_read(room, user)
        except Exception:
            pass


# --------------------------------------------------------------
# Community Discussions Consumer
# Handles WebSocket connections for Academy-wide Community Discussions.
# Real-time event broadcasting (discussion.created, reply.created, pin, lock, etc.)
# --------------------------------------------------------------

class CommunityDiscussionsConsumer(AsyncWebsocketConsumer):
    @database_sync_to_async
    def _get_user_academy_id(self, user):
        if not user or not user.is_authenticated:
            return None
        from users_roles.models import User
        academy_id = User.objects.filter(pk=user.pk).values_list('academy_id', flat=True).first()
        return str(academy_id) if academy_id else None

    async def connect(self):
        self.user = self.scope.get('user')

        # 1. Authenticated User Check
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # 2. Academy Tenant Check (Async-safe DB query)
        academy_id = await self._get_user_academy_id(self.user)
        self.academy_id = academy_id or 'global'
        self.group_name = f'academy_discussions_{self.academy_id}'

        # 3. Join Academy Channel Group
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

    async def receive(self, text_data):
        # Server-push only channel: client messages are ignored safely
        pass

    #--------------------------------------------------------------
    # Group Broadcast Handlers
    #--------------------------------------------------------------

    async def discussion_event(self, event):
        """
        Generic handler for all discussion/reply events pushed from backend REST endpoints.
        """
        await self.send(text_data=json.dumps({
            'type': event['event_type'],
            'event_id': event.get('event_id'),
            'academy_id': event.get('academy_id'),
            'occurred_at': event.get('occurred_at'),
            'data': event.get('data')
        }, default=str))

