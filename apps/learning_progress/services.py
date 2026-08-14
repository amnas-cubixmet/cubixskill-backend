from django.utils import timezone
from enrollments.models import Enrollment, EnrollmentStatus, AccessType
from features.models import CourseFeature
from courses.models import LearningMode

# --------------------------------------------------------------
# Learning Access & Progress Service
# Progress percentages are calculated by the backend and are not trusted
# from client-submitted values.
# Rewatching the same media segment must not inflate watched duration.
# Demo progress is preserved when access upgrades to Full.
# --------------------------------------------------------------

class LearningAccessService:
    @staticmethod
    def can_access_lesson(student, lesson):
        course = lesson.module.course

        # 1. Validate Enrollment
        try:
            enrollment = Enrollment.objects.get(student=student, course=course)
        except Enrollment.DoesNotExist:
            return False, "INVALID_ENROLLMENT", "Student is not enrolled in this course."

        if enrollment.status != EnrollmentStatus.ACTIVE:
            return False, "ENROLLMENT_INACTIVE", f"Enrollment status is {enrollment.status}."

        # Demo lock check
        if enrollment.access_type == AccessType.DEMO and not lesson.is_demo:
            return False, "DEMO_RESTRICTED", "Demo enrollment only grants access to demo lessons."

        # 2. Sequential Unlocking Check
        if course.learning_mode == LearningMode.SEQUENTIAL:
            all_lessons = list(course.modules.prefetch_related('lessons').values_list('lessons__id', flat=True))
            try:
                current_idx = all_lessons.index(lesson.id)
                if current_idx > 0:
                    prev_lesson_id = all_lessons[current_idx - 1]
                    from learning_progress.models import LessonProgress, ProgressStatus
                    prev_completed = LessonProgress.objects.filter(
                        student=student,
                        lesson_id=prev_lesson_id,
                        status=ProgressStatus.COMPLETED
                    ).exists()
                    if not prev_completed:
                        return False, "LESSON_LOCKED", "You must complete previous lessons sequentially first."
            except ValueError:
                pass

        return True, "ALLOWED", "Access granted."
