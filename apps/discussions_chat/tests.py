from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async

from academy.models import Academy
from users_roles.models import User
from courses.models import Course, CourseStatus
from enrollments.models import Enrollment, EnrollmentStatus
from features.models import Feature, FeatureScope, CourseFeature
from features.services import CourseFeatureService
from storage.models import MediaFile, MediaType, MediaStatus
from discussions_chat.models import (
    DiscussionThread,
    DiscussionReply,
    ChatRoom,
    ChatMessage,
    ChatParticipant,
    CommunicationReport,
    ThreadType,
    ThreadStatus,
    RoomType,
    MessageStatus,
    ReportStatus,
)
from discussions_chat.services import DiscussionService, ChatService
from discussions_chat.selectors import DiscussionSelector, ChatSelector
from config.asgi import application

class DiscussionsChatTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # 1. Setup Academy & Users
        self.academy = Academy.objects.create(name="Comm Academy", slug="comm-academy")
        self.staff = User.objects.create_user(
            email="staff@comm.com",
            password="Password123!",
            full_name="Staff Sarah",
            academy=self.academy,
            is_staff=True
        )
        self.student = User.objects.create_user(
            email="student@comm.com",
            password="Password123!",
            full_name="Student Mark"
        )
        self.unregistered_student = User.objects.create_user(
            email="outsider@comm.com",
            password="Password123!",
            full_name="Outsider Alice"
        )

        # 2. Setup Features
        self.feat_disc = Feature.objects.create(
            name="Course Discussions",
            code="course_discussions",
            scope=FeatureScope.COURSE,
            is_active=True
        )
        self.feat_chat = Feature.objects.create(
            name="Course Chat",
            code="course_chat",
            scope=FeatureScope.COURSE,
            is_active=True
        )

        # 3. Setup Course A (Enabled) and Course B (Disabled)
        self.course_a = Course.objects.create(
            academy=self.academy,
            title="Course A (Comm ON)",
            status=CourseStatus.PUBLISHED
        )
        self.course_b = Course.objects.create(
            academy=self.academy,
            title="Course B (Comm OFF)",
            status=CourseStatus.PUBLISHED
        )

        # Enable features on Course A
        CourseFeatureService.enable_feature(self.course_a, "course_discussions", user=self.staff)
        CourseFeatureService.enable_feature(self.course_a, "course_chat", user=self.staff)

        # Disable features on Course B
        CourseFeatureService.disable_feature(self.course_b, "course_discussions", user=self.staff)
        CourseFeatureService.disable_feature(self.course_b, "course_chat", user=self.staff)

        # Enroll student in both courses
        Enrollment.objects.create(student=self.student, course=self.course_a, status=EnrollmentStatus.ACTIVE)
        Enrollment.objects.create(student=self.student, course=self.course_b, status=EnrollmentStatus.ACTIVE)

        # MediaFile sample
        self.media_file = MediaFile.objects.create(
            storage_key="media/sample.png",
            relative_path="media/sample.png",
            original_filename="sample.png",
            stored_filename="sample.png",
            mime_type="image/png",
            media_type=MediaType.IMAGE,
            status=MediaStatus.ACTIVE,
            size_bytes=1024,
            uploaded_by=self.student
        )

    def test_course_feature_entitlement_isolation(self):
        # 1. Student can create thread in Course A where course_discussions is ON
        thread_a = DiscussionService.create_thread(
            course=self.course_a,
            user=self.student,
            title="Course A Discussion",
            content="Hello Course A!"
        )
        self.assertIsNotNone(thread_a.id)

        # 2. Student CANNOT create thread in Course B where course_discussions is OFF
        with self.assertRaises(PermissionDenied):
            DiscussionService.create_thread(
                course=self.course_b,
                user=self.student,
                title="Course B Discussion",
                content="Should fail"
            )

        # 3. Student CANNOT access chat room for Course B
        room_b = ChatService.get_or_create_course_chat_room(self.course_b)
        self.assertFalse(ChatService.validate_chat_access(self.student, room_b))

        room_a = ChatService.get_or_create_course_chat_room(self.course_a)
        self.assertTrue(ChatService.validate_chat_access(self.student, room_a))

    def test_discussion_threads_replies_and_accepted_answer(self):
        # Create Question Thread
        thread = DiscussionService.create_thread(
            course=self.course_a,
            user=self.student,
            title="How to use async python?",
            content="Can someone explain asyncio?",
            thread_type=ThreadType.QUESTION,
            media_file_ids=[str(self.media_file.id)]
        )
        self.assertEqual(thread.attachments.count(), 1)

        # Non-staff cannot post announcement thread
        with self.assertRaises(PermissionDenied):
            DiscussionService.create_thread(
                course=self.course_a,
                user=self.student,
                title="Fake Announcement",
                content="Text",
                thread_type=ThreadType.ANNOUNCEMENT
            )

        # Add reply
        reply = DiscussionService.add_reply(
            thread=thread,
            user=self.staff,
            content="Asyncio uses an event loop to run tasks concurrently."
        )

        thread.refresh_from_db()
        self.assertEqual(thread.reply_count, 1)

        # Accept answer
        updated_thread = DiscussionService.mark_accepted_answer(thread, reply, self.student)
        self.assertEqual(updated_thread.accepted_answer, reply)
        reply.refresh_from_db()
        self.assertTrue(reply.is_answer)

        # Lock thread
        DiscussionService.toggle_lock_thread(thread, self.staff, is_locked=True)
        with self.assertRaises(ValidationError):
            DiscussionService.add_reply(thread, self.student, "Another reply after lock")

    def test_chat_room_messaging_read_state_and_unread_count(self):
        room = ChatService.get_or_create_course_chat_room(self.course_a)

        # Send message 1 from staff
        msg1 = ChatService.send_message(
            room=room,
            user=self.staff,
            content="Welcome to Course A live chat!"
        )

        # Send message 2 from staff
        msg2 = ChatService.send_message(
            room=room,
            user=self.staff,
            content="Please introduce yourselves."
        )

        # Student unread count should be 2
        unread = ChatService.get_unread_count(room, self.student)
        self.assertEqual(unread, 2)

        # Student marks room as read
        ChatService.mark_room_as_read(room, self.student)

        # Unread count should now be 0
        unread_after = ChatService.get_unread_count(room, self.student)
        self.assertEqual(unread_after, 0)

        # Student sends message
        msg3 = ChatService.send_message(
            room=room,
            user=self.student,
            content="Hi, I am Mark!",
            media_file_ids=[str(self.media_file.id)]
        )
        self.assertEqual(msg3.attachments.count(), 1)

    def test_communication_report_submission_and_resolution(self):
        thread = DiscussionService.create_thread(
            course=self.course_a,
            user=self.student,
            title="Inappropriate Title",
            content="Bad content"
        )

        # Submit report
        report = ChatService.create_report(
            user=self.student,
            reason="Spam or inappropriate language",
            thread=thread
        )

        self.assertEqual(report.status, ReportStatus.OPEN)

        # Staff resolves report
        self.client.force_authenticate(user=self.staff)
        url = f"/api/v1/chat/reports/{report.id}/resolve/"
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.RESOLVED)
        self.assertEqual(report.reviewed_by, self.staff)

    def test_discussion_and_chat_rest_api_endpoints(self):
        self.client.force_authenticate(user=self.student)

        # 1. Create Discussion via REST API
        url_create = f"/api/v1/courses/{self.course_a.id}/discussions/"
        resp = self.client.post(url_create, {
            "title": "API Test Thread",
            "content": "Posting thread via REST API",
            "thread_type": "DISCUSSION"
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        thread_id = resp.json()['id']

        # 2. Add Reply via REST API
        url_reply = f"/api/v1/discussions/{thread_id}/replies/"
        resp_reply = self.client.post(url_reply, {
            "content": "API Reply content"
        }, format='json')
        self.assertEqual(resp_reply.status_code, status.HTTP_201_CREATED)

        # 3. List Chat Rooms via REST API
        ChatService.get_or_create_course_chat_room(self.course_a)
        url_rooms = "/api/v1/chat/rooms/"
        resp_rooms = self.client.get(url_rooms)
        self.assertEqual(resp_rooms.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp_rooms.json()), 1)

    async def test_websocket_chat_consumer(self):
        room = await database_sync_to_async(ChatService.get_or_create_course_chat_room)(self.course_a)

        communicator = WebsocketCommunicator(
            application,
            f"/ws/chat/{room.id}/"
        )
        communicator.scope['user'] = self.student

        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

        # Receive participant.joined event
        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'participant.joined')

        # Send message frame
        await communicator.send_json_to({
            'type': 'message.send',
            'content': 'Hello WebSocket Chat!'
        })

        # Receive message.created broadcast
        broadcast = await communicator.receive_json_from()
        self.assertEqual(broadcast['type'], 'message.created')
        self.assertEqual(broadcast['data']['content'], 'Hello WebSocket Chat!')

        await communicator.disconnect()
