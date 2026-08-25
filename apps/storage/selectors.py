import logging
from django.db.models import Q, Sum
from storage.models import MediaFile, MediaStatus

logger = logging.getLogger(__name__)

class MediaUsageSelector:
    @classmethod
    def get_usage(cls, media_file: MediaFile) -> dict:
        """
        Check real domain references across Courses, Lessons, Resources, and Assignments for a MediaFile.
        Returns tenant-safe dictionary with references and counts.
        """
        references = []

        # 1. Check Courses (Thumbnail & Promo Video)
        try:
            from courses.models import Course
            courses = Course.objects.filter(
                Q(thumbnail=media_file) | Q(promo_video=media_file)
            )
            for c in courses:
                ctx = "Course Thumbnail" if c.thumbnail_id == media_file.id else "Course Promo Video"
                references.append({
                    "id": str(c.id),
                    "type": "COURSE",
                    "title": c.title,
                    "context": ctx,
                    "course_id": str(c.id),
                    "lesson_id": None
                })
        except Exception as err:
            logger.warning(f"Error checking Course media usage: {err}")

        # 2. Check LessonMedia
        try:
            from lessons.models import LessonMedia
            lesson_medias = LessonMedia.objects.filter(media_file=media_file).select_related('lesson', 'lesson__module', 'lesson__module__course')
            for lm in lesson_medias:
                if lm.lesson:
                    course = lm.lesson.module.course if (lm.lesson.module and hasattr(lm.lesson.module, 'course')) else None
                    role_str = lm.get_media_role_display() if hasattr(lm, 'get_media_role_display') else str(lm.media_role)
                    references.append({
                        "id": str(lm.id),
                        "type": "LESSON_MEDIA",
                        "title": lm.lesson.title,
                        "context": f"Lesson {role_str}",
                        "course_id": str(course.id) if course else None,
                        "lesson_id": str(lm.lesson.id)
                    })
        except Exception as err:
            logger.warning(f"Error checking LessonMedia usage: {err}")

        # 3. Check LessonResource
        try:
            from lessons.models import LessonResource
            lesson_resources = LessonResource.objects.filter(media_file=media_file).select_related('lesson', 'lesson__module', 'lesson__module__course')
            for lr in lesson_resources:
                if lr.lesson:
                    course = lr.lesson.module.course if (lr.lesson.module and hasattr(lr.lesson.module, 'course')) else None
                    references.append({
                        "id": str(lr.id),
                        "type": "LESSON_RESOURCE",
                        "title": lr.title or lr.lesson.title,
                        "context": f"Resource for {lr.lesson.title}",
                        "course_id": str(course.id) if course else None,
                        "lesson_id": str(lr.lesson.id)
                    })
        except Exception as err:
            logger.warning(f"Error checking LessonResource usage: {err}")

        # 4. Check AssignmentAsset
        try:
            from lessons.models import AssignmentAsset
            assignment_assets = AssignmentAsset.objects.filter(media_file=media_file).select_related('assignment', 'assignment__lesson')
            for aa in assignment_assets:
                if aa.assignment and aa.assignment.lesson:
                    lesson = aa.assignment.lesson
                    references.append({
                        "id": str(aa.id),
                        "type": "ASSIGNMENT_ASSET",
                        "title": aa.title or aa.assignment.title,
                        "context": f"Assignment Asset for {lesson.title}",
                        "course_id": None,
                        "lesson_id": str(lesson.id)
                    })
        except Exception as err:
            logger.warning(f"Error checking AssignmentAsset usage: {err}")

        # 5. Check StudentDocument
        try:
            from students.models import StudentDocument
            student_docs = StudentDocument.objects.filter(media_file=media_file).select_related('student')
            for sd in student_docs:
                student_name = str(sd.student) if sd.student else "Student"
                references.append({
                    "id": str(sd.id),
                    "type": "STUDENT_DOCUMENT",
                    "title": sd.title or "Student Document",
                    "context": f"Document for {student_name}",
                    "course_id": None,
                    "lesson_id": None
                })
        except Exception as err:
            logger.warning(f"Error checking StudentDocument usage: {err}")

        usage_count = len(references)

        return {
            "file_id": str(media_file.id),
            "is_used": usage_count > 0,
            "usage_count": usage_count,
            "references": references
        }


class StorageSummarySelector:
    @classmethod
    def get_summary(cls, academy_uuid) -> dict:
        active_files = MediaFile.objects.filter(academy_uuid=academy_uuid).exclude(status=MediaStatus.DELETED)
        used_bytes = active_files.aggregate(s=Sum('size_bytes'))['s'] or 0

        from storage.services import StorageService
        account = StorageService.get_or_create_account(academy_uuid)
        if account.current_usage_bytes != used_bytes:
            account.current_usage_bytes = used_bytes
            account.save(update_fields=['current_usage_bytes'])

        return {
            "used_bytes": used_bytes,
            "total_files_count": active_files.count()
        }
