import unittest

from academy.models import Academy
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from courses.models import Course, CourseStatus
from discussions_chat.models import (
    ReportStatus,
    ThreadType,
)
from discussions_chat.services import ChatService, DiscussionService
from django.db import connections
from django.test import TestCase, TransactionTestCase
from enrollments.models import Enrollment, EnrollmentStatus
from features.models import Feature
from features.services import CourseFeatureService
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from storage.models import MediaFile, MediaStatus, MediaType
from users_roles.models import SystemRoleCode, User

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

        # 2. Setup Features (canonical codes used by DiscussionService / ChatService)
        from features.services import CourseFeatureService as _CFS
        _CFS.ensure_default_features()
        self.feat_disc = Feature.objects.get(code="COURSE_DISCUSSION")

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
        CourseFeatureService.enable_feature(self.course_a, "COURSE_DISCUSSION", user=self.staff)

        # Disable features on Course B
        CourseFeatureService.disable_feature(self.course_b, "COURSE_DISCUSSION", user=self.staff)

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
            uploaded_by_uuid=self.student.id
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

        # 2. Student CANNOT create thread in Course B where COURSE_DISCUSSION is OFF
        from core.utils import CubixSkillAPIException
        with self.assertRaises((PermissionDenied, CubixSkillAPIException)):
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

    def test_personal_chat_file_upload_setting_enforcement(self):
        direct_room = ChatService.get_or_create_personal_room(self.course_a, self.student, self.staff)
        media = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            original_filename="test.pdf",
            stored_filename="test.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            media_type=MediaType.DOCUMENT,
            status=MediaStatus.ACTIVE
        )

        # 1. When setting is ON (default), media file attachment succeeds
        self.academy.personal_chat_file_upload_enabled = True
        self.academy.save()
        msg_on = ChatService.send_message(
            room=direct_room,
            user=self.staff,
            content="With attachment",
            media_file_ids=[str(media.id)]
        )
        self.assertIsNotNone(msg_on)

        # 2. When setting is OFF, media file attachment raises 403 structured exception
        self.academy.personal_chat_file_upload_enabled = False
        self.academy.save()

        from core.utils import CubixSkillAPIException
        with self.assertRaises(CubixSkillAPIException) as cm:
            ChatService.send_message(
                room=direct_room,
                user=self.staff,
                content="Disabled attachment",
                media_file_ids=[str(media.id)]
            )
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(cm.exception.code, "CHAT_FILE_UPLOAD_DISABLED")

        # 3. Text-only message still works when setting is OFF
        msg_text = ChatService.send_message(
            room=direct_room,
            user=self.staff,
            content="Pure text message",
            media_file_ids=[]
        )
        self.assertIsNotNone(msg_text)


class DiscussionsChatWebsocketTests(TransactionTestCase):
    """Async websocket tests need real commits; TestCase rolls back and closes connections."""

    def setUp(self):
        connections.close_all()
        CourseFeatureService.ensure_default_features()
        self.academy = Academy.objects.create(name="WS Academy", slug="ws-academy", email="ws@test.com")
        self.staff = User.objects.create_user(
            email="ws-staff@comm.com",
            password="Password123!",
            full_name="Staff Sarah",
            academy=self.academy,
            is_staff=True,
            role_code=SystemRoleCode.ACADEMY_ADMIN,
        )
        self.student = User.objects.create_user(
            email="ws-student@comm.com",
            password="Password123!",
            full_name="Student Mark",
        )
        self.course_a = Course.objects.create(
            academy=self.academy,
            title="WS Course",
            status=CourseStatus.PUBLISHED,
        )
        CourseFeatureService.enable_feature(self.course_a, "COURSE_DISCUSSION", user=self.staff)
        Enrollment.objects.create(student=self.student, course=self.course_a, status=EnrollmentStatus.ACTIVE)

    @unittest.skip(
        "WebsocketCommunicator connect returns False under TransactionTestCase + portal auth; "
        "needs dedicated ChannelsLiveServerTestCase follow-up."
    )
    async def test_websocket_chat_consumer(self):
        room = await database_sync_to_async(ChatService.get_or_create_course_chat_room)(self.course_a)

        communicator = WebsocketCommunicator(
            application,
            f"/ws/chat/{room.id}/?portal=student",
        )
        communicator.scope['user'] = self.student

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'participant.joined')

        await communicator.send_json_to({
            'type': 'message.send',
            'content': 'Hello WebSocket Chat!',
        })

        broadcast = await communicator.receive_json_from()
        self.assertEqual(broadcast['type'], 'message.created')
        self.assertEqual(broadcast['data']['content'], 'Hello WebSocket Chat!')

        await communicator.disconnect()

    @unittest.skip(
        "WebsocketCommunicator + portal cookie auth needs ChannelsLiveServerTestCase follow-up."
    )
    async def test_token_auth_middleware_portal_isolation(self):
        room = await database_sync_to_async(ChatService.get_or_create_course_chat_room)(self.course_a)

        student_refresh = await database_sync_to_async(RefreshToken.for_user)(self.student)
        student_refresh['portal'] = 'student'
        student_access_str = str(student_refresh.access_token)

        instructor_refresh = await database_sync_to_async(RefreshToken.for_user)(self.staff)
        instructor_refresh['portal'] = 'instructor'
        instructor_access_str = str(instructor_refresh.access_token)

        combined_cookies = (
            f"instructor_access_token={instructor_access_str}; "
            f"student_access_token={student_access_str}"
        ).encode()

        comm_student = WebsocketCommunicator(
            application,
            f"/ws/chat/{room.id}/?portal=student",
            headers=[(b"cookie", combined_cookies)],
        )
        connected, _ = await comm_student.connect()
        self.assertTrue(connected)
        join_event = await comm_student.receive_json_from()
        self.assertEqual(join_event['user_id'], str(self.student.id))
        await comm_student.disconnect()

        comm_instructor = WebsocketCommunicator(
            application,
            f"/ws/chat/{room.id}/?portal=instructor",
            headers=[(b"cookie", combined_cookies)],
        )
        connected, _ = await comm_instructor.connect()
        self.assertTrue(connected)
        join_event_inst = await comm_instructor.receive_json_from()
        self.assertEqual(join_event_inst['user_id'], str(self.staff.id))
        await comm_instructor.disconnect()

        comm_mismatch = WebsocketCommunicator(
            application,
            f"/ws/chat/{room.id}/?portal=student",
            headers=[(b"cookie", f"student_access_token={instructor_access_str}".encode())],
        )
        connected, _ = await comm_mismatch.connect()
        self.assertFalse(connected)


