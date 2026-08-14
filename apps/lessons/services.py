from django.db import transaction, models
from lessons.models import Lesson, LessonMedia, LessonRichText, Quiz, Question, QuestionOption, Assignment, AssignmentAsset, LessonType
from modules.models import Module
from storage.models import MediaFile
from core.utils import CubixSkillAPIException

#--------------------------------------------------------------
# Lesson Services
#--------------------------------------------------------------

class LessonService:
    @staticmethod
    @transaction.atomic
    def create_lesson(module: Module, title: str, lesson_type: str, description: str = '', duration_minutes: int = 0, is_demo: bool = False, allow_download: bool = False, external_url: str = '') -> Lesson:
        if lesson_type == LessonType.URL and not external_url:
            raise CubixSkillAPIException("External URL is required for URL lesson type.", code="URL_REQUIRED")

        max_order = Lesson.objects.filter(module=module).aggregate(models.Max('order_index'))['order_index__max'] or 0
        lesson = Lesson.objects.create(
            module=module,
            title=title,
            lesson_type=lesson_type,
            description=description,
            duration_minutes=duration_minutes,
            is_demo=is_demo,
            allow_download=allow_download,
            external_url=external_url,
            order_index=max_order + 1
        )
        return lesson

    @staticmethod
    @transaction.atomic
    def reorder_lessons(module: Module, lessons_order: list) -> None:
        valid_ids = set(Lesson.objects.filter(module=module).values_list('id', flat=True))
        for item in lessons_order:
            lesson_id = item.get('id')
            new_order = item.get('order_index')
            if lesson_id and new_order is not None and str(lesson_id) in [str(vid) for vid in valid_ids]:
                Lesson.objects.filter(id=lesson_id, module=module).update(order_index=new_order)

    @staticmethod
    def attach_media(lesson: Lesson, media_file: MediaFile, media_role: str = 'PRIMARY', caption: str = '') -> LessonMedia:
        return LessonMedia.objects.create(
            lesson=lesson,
            media_file=media_file,
            media_role=media_role,
            caption=caption
        )

    @staticmethod
    def set_rich_text(lesson: Lesson, content: str) -> LessonRichText:
        rich_text, _ = LessonRichText.objects.update_or_create(
            lesson=lesson,
            defaults={'content': content}
        )
        return rich_text

    @staticmethod
    def create_quiz(lesson: Lesson, title: str, instructions: str = '', passing_score: int = 70, time_limit_minutes: int = None) -> Quiz:
        if lesson.lesson_type != LessonType.QUIZ:
            raise CubixSkillAPIException("Lesson type must be QUIZ to create a quiz.", code="INVALID_TYPE")

        return Quiz.objects.create(
            lesson=lesson,
            title=title,
            instructions=instructions,
            passing_score=passing_score,
            time_limit_minutes=time_limit_minutes
        )

    @staticmethod
    def create_assignment(lesson: Lesson, title: str, instructions: str, due_date=None, max_marks: int = 100) -> Assignment:
        if lesson.lesson_type != LessonType.ASSIGNMENT:
            raise CubixSkillAPIException("Lesson type must be ASSIGNMENT to create an assignment.", code="INVALID_TYPE")

        return Assignment.objects.create(
            lesson=lesson,
            title=title,
            instructions=instructions,
            due_date=due_date,
            max_marks=max_marks
        )
