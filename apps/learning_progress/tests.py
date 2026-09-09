from academy.models import Academy
from courses.models import Course
from django.test import TestCase
from enrollments.models import Enrollment, EnrollmentStatus
from features.services import CourseFeatureService
from learning_progress.models import LessonProgress, ProgressStatus
from learning_progress.services import StudentCourseProgressionService
from lessons.models import Lesson
from modules.models import Module
from users_roles.models import User


class StudentCourseProgressionServiceTest(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(name="Test Academy", slug="test-academy")
        self.course = Course.objects.create(academy=self.academy, title="Test Course", slug="test-course")
        self.user = User.objects.create_user(email="student1@example.com", password="password123")
        self.enrollment = Enrollment.objects.create(student=self.user, course=self.course, status=EnrollmentStatus.ACTIVE)

        self.module1 = Module.objects.create(course=self.course, title="Module 1", order_index=1)
        self.lesson1 = Lesson.objects.create(module=self.module1, title="Lesson 1", order_index=1, lesson_type="VIDEO")
        self.lesson2 = Lesson.objects.create(module=self.module1, title="Lesson 2", order_index=2, lesson_type="VIDEO")

        self.module2 = Module.objects.create(course=self.course, title="Module 2", order_index=2)
        self.lesson3 = Lesson.objects.create(module=self.module2, title="Lesson 3", order_index=1, lesson_type="VIDEO")

    def test_progression_when_locking_disabled(self):
        progression = StudentCourseProgressionService.get_student_course_progression(self.user, self.course)
        self.assertFalse(progression['lesson_locking_enabled'])
        self.assertTrue(progression['lessons_map'][str(self.lesson1.id)]['unlocked'])
        self.assertTrue(progression['lessons_map'][str(self.lesson2.id)]['unlocked'])
        self.assertTrue(progression['lessons_map'][str(self.lesson3.id)]['unlocked'])

    def test_progression_when_locking_enabled(self):
        CourseFeatureService.enable_feature(self.course, 'LESSON_LOCKING_REPORT')
        progression = StudentCourseProgressionService.get_student_course_progression(self.user, self.course)
        self.assertTrue(progression['lesson_locking_enabled'])

        # Lesson 1 is unlocked, Lesson 2 and 3 are locked
        self.assertTrue(progression['lessons_map'][str(self.lesson1.id)]['unlocked'])
        self.assertFalse(progression['lessons_map'][str(self.lesson2.id)]['unlocked'])
        self.assertFalse(progression['lessons_map'][str(self.lesson3.id)]['unlocked'])

        # Complete Lesson 1
        LessonProgress.objects.create(student=self.user, lesson=self.lesson1, status=ProgressStatus.COMPLETED)

        progression2 = StudentCourseProgressionService.get_student_course_progression(self.user, self.course)
        self.assertTrue(progression2['lessons_map'][str(self.lesson1.id)]['completed'])
        self.assertTrue(progression2['lessons_map'][str(self.lesson2.id)]['unlocked'])
        self.assertFalse(progression2['lessons_map'][str(self.lesson3.id)]['unlocked'])
