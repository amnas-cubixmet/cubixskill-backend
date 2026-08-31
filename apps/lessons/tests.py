from django.test import TestCase
from rest_framework.exceptions import ValidationError
from academy.models import Academy
from courses.models import Course
from modules.models import Module
from lessons.models import Lesson, LessonType
from lessons.serializers import LessonSerializer, LessonCreateSerializer
from lessons.url_validators import validate_audio_url
from users_roles.models import User, SystemRoleCode

class AudioLessonSourceTests(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(name="Test Audio Academy", slug="test-audio-academy")
        self.user = User.objects.create_user(
            email="instructor_audio@example.com",
            password="Password123!",
            academy=self.academy,
            role_code=SystemRoleCode.ACADEMY_ADMIN
        )
        self.course = Course.objects.create(
            academy=self.academy,
            title="Audio Test Course"
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Audio Module"
        )

    def test_audio_lesson_with_url_source_serializer(self):
        lesson = Lesson.objects.create(
            module=self.module,
            title="Audio 1",
            lesson_type=LessonType.AUDIO,
            external_url="https://example.com/audio/lesson-01.mp3"
        )

        serializer = LessonSerializer(lesson)
        data = serializer.data

        self.assertEqual(data['title'], "Audio 1")
        self.assertEqual(data['lesson_type'], "AUDIO")
        self.assertEqual(data['external_url'], "https://example.com/audio/lesson-01.mp3")
        self.assertEqual(data['audio_url'], "https://example.com/audio/lesson-01.mp3")

    def test_audio_lesson_create_serializer_url_source(self):
        serializer = LessonCreateSerializer(data={
            "title": "Audio URL Lesson",
            "lesson_type": "AUDIO",
            "content_source": "url",
            "external_url": "https://cdn.example.com/audio/podcast.mp3"
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        validated = serializer.validated_data
        self.assertEqual(validated['external_url'], "https://cdn.example.com/audio/podcast.mp3")

    def test_validate_audio_url_valid_formats(self):
        valid_urls = [
            "https://example.com/media/audio/lesson-01.mp3",
            "https://cdn.example.com/audio/chapter-2.m4a",
            "https://files.example.com/course/audio/topic.ogg",
            "https://media.example.com/lecture.wav",
            "https://cdn.example.com/media/12345.mp3?token=abc"
        ]
        for url in valid_urls:
            self.assertEqual(validate_audio_url(url), url.strip())

    def test_validate_audio_url_invalid_schemes(self):
        invalid_urls = [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:audio/mp3;base64,123",
            "ftp://example.com/audio.mp3"
        ]
        for url in invalid_urls:
            with self.assertRaises(ValidationError):
                validate_audio_url(url)

    def test_validate_audio_url_ssrf_protection(self):
        ssrf_urls = [
            "http://127.0.0.1/audio.mp3",
            "http://localhost/audio.mp3",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/audio.mp3",
            "http://192.168.1.1/audio.mp3"
        ]
        for url in ssrf_urls:
            with self.assertRaises(ValidationError):
                validate_audio_url(url)

    def test_validate_audio_url_generic_webpage_rejection(self):
        webpage_urls = [
            "https://example.com/audio-page",
            "https://example.com/course/lesson.html"
        ]
        for url in webpage_urls:
            with self.assertRaises(ValidationError) as ctx:
                validate_audio_url(url)
            self.assertIn("webpage", str(ctx.exception).lower())

class QuizEndToEndTests(TestCase):
    def setUp(self):
        from lessons.services import LessonService
        from lessons.models import Quiz, Question, QuestionOption

        self.academy_a = Academy.objects.create(name="Academy A", slug="academy-a")
        self.user_a = User.objects.create_user(
            email="admin_a@example.com",
            password="Password123!",
            academy=self.academy_a,
            role_code=SystemRoleCode.ACADEMY_ADMIN
        )

        self.academy_b = Academy.objects.create(name="Academy B", slug="academy-b")
        self.user_b = User.objects.create_user(
            email="admin_b@example.com",
            password="Password123!",
            academy=self.academy_b,
            role_code=SystemRoleCode.ACADEMY_ADMIN
        )

        self.course_a = Course.objects.create(academy=self.academy_a, title="Course A")
        self.module_a = Module.objects.create(course=self.course_a, title="Module A")

    def test_create_quiz_lesson_with_questions_and_options(self):
        from lessons.services import LessonService
        lesson = LessonService.create_lesson(
            module=self.module_a,
            title="Final Assessment Quiz",
            lesson_type=LessonType.QUIZ,
            description="Testing quiz creation"
        )
        quiz_payload = {
            "title": "Final Assessment Quiz",
            "instructions": "Answer all questions",
            "passingScore": 80,
            "timeLimitMinutes": 45,
            "maxAttempts": 2,
            "questions": [
                {
                    "questionText": "What is Python?",
                    "type": "SINGLE_CHOICE",
                    "points": 5,
                    "options": [
                        {"text": "A snakes family", "isCorrect": False},
                        {"text": "A programming language", "isCorrect": True}
                    ]
                },
                {
                    "questionText": "State True or False: Django is written in Python.",
                    "type": "TRUE_FALSE",
                    "points": 2,
                    "options": [
                        {"text": "True", "isCorrect": True},
                        {"text": "False", "isCorrect": False}
                    ]
                }
            ]
        }
        quiz = LessonService.save_quiz_data(lesson, quiz_payload)
        self.assertEqual(quiz.title, "Final Assessment Quiz")
        self.assertEqual(quiz.passing_score, 80)
        self.assertEqual(quiz.time_limit_minutes, 45)
        self.assertEqual(quiz.questions.count(), 2)

        q1 = quiz.questions.first()
        self.assertEqual(q1.question_text, "What is Python?")
        self.assertEqual(q1.options.count(), 2)
        correct_opt = q1.options.get(is_correct=True)
        self.assertEqual(correct_opt.option_text, "A programming language")

    def test_quiz_update_replaces_questions_atomically(self):
        from lessons.services import LessonService
        lesson = LessonService.create_lesson(
            module=self.module_a,
            title="Draft Quiz",
            lesson_type=LessonType.QUIZ
        )
        quiz_payload_v1 = {
            "title": "Draft Quiz",
            "questions": [
                {
                    "questionText": "Initial Question",
                    "type": "SINGLE_CHOICE",
                    "options": [
                        {"text": "Opt 1", "isCorrect": True},
                        {"text": "Opt 2", "isCorrect": False}
                    ]
                }
            ]
        }
        LessonService.save_quiz_data(lesson, quiz_payload_v1)

        # Update quiz
        quiz_payload_v2 = {
            "title": "Updated Quiz Title",
            "passingScore": 90,
            "questions": [
                {
                    "questionText": "Updated Question 1",
                    "type": "SHORT_ANSWER",
                    "answerText": "Expected short answer"
                }
            ]
        }
        updated_quiz = LessonService.save_quiz_data(lesson, quiz_payload_v2)
        self.assertEqual(updated_quiz.title, "Updated Quiz Title")
        self.assertEqual(updated_quiz.passing_score, 90)
        self.assertEqual(updated_quiz.questions.count(), 1)
        self.assertEqual(updated_quiz.questions.first().question_text, "Updated Question 1")

    def test_post_quiz_lesson_with_wrapped_content_success(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        payload = {
            "title": "API Quiz Lesson",
            "lesson_type": "QUIZ",
            "description": "Created via API",
            "duration_minutes": 15,
            "is_demo": False,
            "content": {
                "quizPayload": {
                    "title": "API Quiz Lesson",
                    "instructions": "API instructions",
                    "passingScore": 85,
                    "timeLimitMinutes": 20,
                    "maxAttempts": 3,
                    "shuffleQuestions": True,
                    "showResult": True,
                    "questions": [
                        {
                            "questionText": "What is 2 + 2?",
                            "question_type": "SINGLE_CHOICE",
                            "points": 1,
                            "options": [
                                {"option_text": "3", "is_correct": False},
                                {"option_text": "4", "is_correct": True}
                            ]
                        }
                    ]
                }
            }
        }

        url = f"/api/v1/lessons/modules/{self.module_a.id}/lessons/"
        response = client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('quiz', response.data['data'])
        self.assertEqual(response.data['data']['quiz']['title'], "API Quiz Lesson")

    def test_post_quiz_lesson_with_invalid_data_returns_400_and_rolls_back(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        initial_lesson_count = Lesson.objects.count()

        payload = {
            "title": "Invalid Quiz Lesson",
            "lesson_type": "QUIZ",
            "content": {
                "quizPayload": {
                    "title": "Invalid Quiz",
                    "questions": [
                        {
                            "questionText": "",  # Empty question text!
                            "question_type": "SINGLE_CHOICE",
                            "options": [{"option_text": "A", "is_correct": True}]
                        }
                    ]
                }
            }
        }

        url = f"/api/v1/lessons/modules/{self.module_a.id}/lessons/"
        response = client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 400)
        # Verify complete transaction rollback: no orphan Lesson created!
        self.assertEqual(Lesson.objects.count(), initial_lesson_count)


class AssignmentEndToEndTests(TestCase):
    def setUp(self):
        from academy.models import Academy
        from users_roles.models import User, SystemRoleCode
        from courses.models import Course
        from modules.models import Module
        from storage.models import MediaFile

        self.academy_a = Academy.objects.create(name="Academy Assignment", slug="academy-assignment")
        self.user_a = User.objects.create_user(
            email="instructor_assign@example.com",
            password="Password123!",
            academy=self.academy_a,
            role_code="INSTRUCTOR"
        )
        self.course_a = Course.objects.create(
            academy=self.academy_a,
            title="React Assignment Course",
            slug="react-assignment-course"
        )
        self.module_a = Module.objects.create(
            course=self.course_a,
            title="Module Assignment",
            order_index=1
        )
        self.media_file = MediaFile.objects.create(
            academy_uuid=self.academy_a.id,
            uploaded_by_uuid=self.user_a.id,
            original_filename="assignment-brief.pdf",
            size_bytes=1048576,
            mime_type="application/pdf",
            media_type="DOCUMENT",
            storage_path="documents/brief.pdf"
        )

    def test_post_assignment_lesson_with_attachment_success(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        payload = {
            "title": "Build a Todo App",
            "lesson_type": "ASSIGNMENT",
            "description": "Create a todo app using React 19",
            "duration_minutes": 60,
            "is_demo": False,
            "content": {
                "assignmentPayload": {
                    "title": "Build a Todo App",
                    "instructions": "Follow the attached assignment PDF instructions.",
                    "max_marks": 100,
                    "allow_file_submission": True,
                    "allow_text_submission": True,
                    "assets": [
                        {
                            "media_file_id": str(self.media_file.id),
                            "title": "Assignment Brief PDF",
                            "asset_type": "DOCUMENT"
                        }
                    ]
                }
            }
        }

        url = f"/api/v1/lessons/modules/{self.module_a.id}/lessons/"
        response = client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('assignment', response.data['data'])
        assignment_data = response.data['data']['assignment']
        self.assertEqual(assignment_data['title'], "Build a Todo App")
        self.assertEqual(assignment_data['max_marks'], 100)
        self.assertEqual(len(assignment_data['assets']), 1)
        self.assertEqual(assignment_data['assets'][0]['title'], "Assignment Brief PDF")

    def test_post_assignment_lesson_without_attachment_success(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        payload = {
            "title": "Text Only Assignment",
            "lesson_type": "ASSIGNMENT",
            "description": "Short essay assignment",
            "duration_minutes": 30,
            "content": {
                "assignmentPayload": {
                    "title": "Text Only Assignment",
                    "instructions": "Write 200 words on React hooks.",
                    "max_marks": 50
                }
            }
        }

        url = f"/api/v1/lessons/modules/{self.module_a.id}/lessons/"
        response = client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('assignment', response.data['data'])
        self.assertEqual(response.data['data']['assignment']['max_marks'], 50)
        self.assertEqual(len(response.data['data']['assignment']['assets']), 0)

    def test_post_assignment_lesson_with_due_days_success(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        payload = {
            "title": "Due Days Assignment",
            "lesson_type": "ASSIGNMENT",
            "description": "7 days assignment",
            "content": {
                "assignmentPayload": {
                    "title": "Due Days Assignment",
                    "instructions": "Complete in 7 days.",
                    "due_days": 7,
                    "max_marks": 100
                }
            }
        }

        url = f"/api/v1/lessons/modules/{self.module_a.id}/lessons/"
        response = client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['data']['assignment']['due_days'], 7)

    def test_post_assignment_lesson_with_zero_or_negative_due_days_returns_400(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        for invalid_val in [0, -5, "abc"]:
            payload = {
                "title": "Invalid Due Days Assignment",
                "lesson_type": "ASSIGNMENT",
                "content": {
                    "assignmentPayload": {
                        "title": "Invalid Due Days",
                        "instructions": "Test invalid due days",
                        "due_days": invalid_val
                    }
                }
            }

            url = f"/api/v1/lessons/modules/{self.module_a.id}/lessons/"
            response = client.post(url, payload, format='json')
            self.assertEqual(response.status_code, 400)

    def test_update_assignment_lesson_due_days_clear_or_change(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user_a)

        # Create initial with due_days = 7
        payload = {
            "title": "Update Due Days Assignment",
            "lesson_type": "ASSIGNMENT",
            "content": {
                "assignmentPayload": {
                    "title": "Update Due Days Assignment",
                    "instructions": "Initial",
                    "due_days": 7
                }
            }
        }
        url = f"/api/v1/lessons/modules/{self.module_a.id}/lessons/"
        res_create = client.post(url, payload, format='json')
        self.assertEqual(res_create.status_code, 201)
        lesson_uuid = res_create.data['data']['id']

        # Update due_days = 14
        update_payload = {
            "content": {
                "assignmentPayload": {
                    "title": "Updated",
                    "instructions": "Updated",
                    "due_days": 14
                }
            }
        }
        res_update = client.patch(f"/api/v1/lessons/{lesson_uuid}/", update_payload, format='json')
        self.assertEqual(res_update.status_code, 200)
        data_update = res_update.data.get('data', res_update.data)
        self.assertEqual(data_update['assignment']['due_days'], 14)

        # Clear due_days = null
        clear_payload = {
            "content": {
                "assignmentPayload": {
                    "title": "Cleared",
                    "instructions": "Cleared",
                    "due_days": None
                }
            }
        }
        res_clear = client.patch(f"/api/v1/lessons/{lesson_uuid}/", clear_payload, format='json')
        self.assertEqual(res_clear.status_code, 200)
        data_clear = res_clear.data.get('data', res_clear.data)
        self.assertIsNone(data_clear['assignment']['due_days'])

