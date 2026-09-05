import logging
from django.utils import timezone
from enrollments.models import Enrollment, EnrollmentStatus, AccessType
from features.services import CourseFeatureService
from modules.models import Module
from lessons.models import Lesson
from learning_progress.models import LessonProgress, ProgressStatus, CourseProgress

logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# Student Course Progression & Lesson Locking Service
# Computes sequential lesson unlock states per student & course
# --------------------------------------------------------------

class StudentCourseProgressionService:

    @staticmethod
    def is_lesson_locking_enabled(course) -> bool:
        if not course:
            return False
        if getattr(course, 'learning_mode', None) == 'SEQUENTIAL':
            return True
        return CourseFeatureService.has_feature(course, 'LESSON_LOCKING')

    @staticmethod
    def get_student_course_progression(student, course) -> dict:
        """
        Computes ordered lesson lock/completion state for a student in a course.
        Returns:
        {
          'lesson_locking_enabled': bool,
          'resume_lesson_id': str | None,
          'lessons_map': {
              lesson_id_str: {
                  'completed': bool,
                  'unlocked': bool,
                  'lock_reason': str | None,
                  'required_lesson': {'id': str, 'title': str} | None
              }
          }
        }
        """
        locking_enabled = StudentCourseProgressionService.is_lesson_locking_enabled(course)

        modules = Module.objects.filter(course=course, is_active=True).order_by('order_index')
        ordered_lessons = []
        for mod in modules:
            mod_lessons = list(mod.lessons.filter(is_active=True).order_by('order_index'))
            ordered_lessons.extend(mod_lessons)

        completed_lesson_ids = set(
            LessonProgress.objects.filter(
                student=student,
                lesson__module__course=course,
                status=ProgressStatus.COMPLETED
            ).values_list('lesson_id', flat=True)
        )

        lessons_map = {}
        resume_lesson_id = None
        previous_required_completed = True

        for les in ordered_lessons:
            les_id_str = str(les.id)
            is_completed = les.id in completed_lesson_ids

            if not locking_enabled:
                unlocked = True
                lock_reason = None
                required_lesson = None
            else:
                manual_locked = getattr(les, 'is_locked', False)
                if manual_locked:
                    unlocked = False
                    lock_reason = 'MANUALLY_LOCKED'
                    required_lesson = None
                elif is_completed:
                    unlocked = True
                    lock_reason = None
                    required_lesson = None
                    previous_required_completed = True
                elif previous_required_completed:
                    unlocked = True
                    lock_reason = None
                    required_lesson = None
                    previous_required_completed = False
                    if resume_lesson_id is None:
                        resume_lesson_id = les_id_str
                else:
                    unlocked = False
                    lock_reason = 'PREVIOUS_LESSON_INCOMPLETE'
                    idx = ordered_lessons.index(les)
                    req_les = ordered_lessons[idx - 1] if idx > 0 else None
                    required_lesson = {'id': str(req_les.id), 'title': req_les.title} if req_les else None

            lessons_map[les_id_str] = {
                'completed': is_completed,
                'unlocked': unlocked,
                'lock_reason': lock_reason,
                'required_lesson': required_lesson,
            }

        if resume_lesson_id is None and ordered_lessons:
            first_uncompleted = next((str(l.id) for l in ordered_lessons if l.id not in completed_lesson_ids), None)
            resume_lesson_id = first_uncompleted or str(ordered_lessons[0].id)

        return {
            'lesson_locking_enabled': locking_enabled,
            'resume_lesson_id': resume_lesson_id,
            'lessons_map': lessons_map,
        }

    @staticmethod
    def can_student_access_lesson(student, course, lesson):
        """
        Validates if student can access private lesson content.
        Returns tuple: (can_access: bool, code: str, detail: str, required_lesson: dict | None)
        """
        try:
            enrollment = Enrollment.objects.get(
                student=student,
                course=course,
                status__in=[EnrollmentStatus.ACTIVE, EnrollmentStatus.EXPIRED]
            )
        except Enrollment.DoesNotExist:
            return False, "NOT_ENROLLED", "You are not enrolled in this course.", None

        if enrollment.status == EnrollmentStatus.EXPIRED:
            return False, "ENROLLMENT_EXPIRED", "Your enrollment in this course has expired.", None

        if enrollment.access_type == AccessType.DEMO and not getattr(lesson, 'is_demo', False):
            return False, "DEMO_RESTRICTED", "Demo enrollment only grants access to demo lessons.", None

        if not StudentCourseProgressionService.is_lesson_locking_enabled(course):
            return True, "ALLOWED", "Access granted.", None

        progression = StudentCourseProgressionService.get_student_course_progression(student, course)
        les_id_str = str(lesson.id)
        les_access = progression['lessons_map'].get(les_id_str)

        if les_access and not les_access['unlocked']:
            req_les = les_access.get('required_lesson')
            req_title = f' "{req_les["title"]}"' if req_les and req_les.get('title') else ''
            return False, "LESSON_LOCKED", f"Complete the previous lesson{req_title} to unlock this lesson.", req_les

        return True, "ALLOWED", "Access granted.", None


class LearningAccessService:
    @staticmethod
    def can_access_lesson(student, lesson):
        course = lesson.module.course
        can_access, code, detail, _ = StudentCourseProgressionService.can_student_access_lesson(student, course, lesson)
        return can_access, code, detail

