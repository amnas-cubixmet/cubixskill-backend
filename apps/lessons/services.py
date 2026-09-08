from core.utils import CubixSkillAPIException
from django.db import models, transaction
from lessons.models import (
    Assignment,
    AssignmentAsset,
    Lesson,
    LessonMedia,
    LessonResource,
    LessonRichText,
    LessonType,
    Question,
    QuestionOption,
    QuestionType,
    Quiz,
)
from modules.models import Module
from storage.models import MediaFile

#--------------------------------------------------------------
# Lesson Duration & Preview Calculation Helpers
#--------------------------------------------------------------

def get_lesson_actual_duration_seconds(lesson) -> int:
    """
    Computes real duration in seconds for a lesson.
    Checks attached primary MediaFile.duration_seconds first,
    or falls back to lesson.duration_minutes * 60.
    """
    primary = lesson.media_files.filter(media_role='PRIMARY').first()
    if primary and primary.media_file and primary.media_file.duration_seconds > 0:
        return int(float(primary.media_file.duration_seconds))
    if getattr(lesson, 'duration_minutes', 0) > 0:
        return int(lesson.duration_minutes * 60)
    return 0

def get_public_preview_duration_seconds(actual_duration_seconds: float) -> int:
    """
    Canonical public preview duration formula:
    - If actual_duration_seconds > 300 (5 minutes): return 300 (5 minutes limit)
    - If actual_duration_seconds <= 300: return actual_duration_seconds / 2 (50% limit)
    """
    if not actual_duration_seconds or actual_duration_seconds <= 0:
        return 0
    if actual_duration_seconds > 300:
        return 300
    return int(actual_duration_seconds / 2)


#--------------------------------------------------------------
# Lesson Services
#--------------------------------------------------------------

class LessonService:
    @staticmethod
    @transaction.atomic
    def create_lesson(module: Module, title: str, lesson_type: str, description: str = '', duration_minutes: int = 0, is_demo: bool = False, is_locked: bool = False, allow_download: bool = False, external_url: str = '') -> Lesson:
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
            is_locked=is_locked,
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
    def detach_media(lesson: Lesson, media_id: str = None) -> None:
        qs = LessonMedia.objects.filter(lesson=lesson)
        if media_id:
            qs = qs.filter(id=media_id)
        qs.delete()

    @staticmethod
    @transaction.atomic
    def save_resources_data(lesson: Lesson, resources_data: list) -> list:
        if not isinstance(resources_data, list):
            return []

        created_resources = []
        for idx, res_item in enumerate(resources_data):
            if not isinstance(res_item, dict):
                continue
            media_file_id = res_item.get('media_file_id') or res_item.get('media_file') or res_item.get('mediaFileId')
            title = (res_item.get('title') or '').strip()
            url = (res_item.get('url') or '').strip()
            description = (res_item.get('description') or '').strip()
            resource_type = res_item.get('resource_type') or res_item.get('resourceType') or res_item.get('asset_type') or 'document'
            allow_download = bool(res_item.get('allow_download', False) or res_item.get('allowDownload', False))

            media_file = None
            if media_file_id:
                try:
                    media_file = MediaFile.objects.get(id=media_file_id)
                    if lesson.module and lesson.module.course and lesson.module.course.academy:
                        if media_file.academy_uuid != lesson.module.course.academy.id:
                            raise CubixSkillAPIException(
                                "Permission denied: Cannot attach media from another Academy as a resource.",
                                code="CROSS_ACADEMY_MEDIA_FORBIDDEN",
                                status_code=403
                            )
                except MediaFile.DoesNotExist:
                    raise CubixSkillAPIException("MediaFile not found for resource.", code="NOT_FOUND", status_code=404)

            if not media_file and not url:
                continue

            if not title:
                title = media_file.original_filename if media_file else 'Resource Attachment'

            resource = LessonResource.objects.create(
                lesson=lesson,
                media_file=media_file,
                title=title,
                url=url,
                description=description,
                resource_type=resource_type,
                allow_download=allow_download,
                order_index=idx
            )
            created_resources.append(resource)
        return created_resources

    @staticmethod
    @transaction.atomic
    def save_quiz_data(lesson: Lesson, quiz_data: dict) -> Quiz:
        if lesson.lesson_type != LessonType.QUIZ:
            raise CubixSkillAPIException("Lesson type must be QUIZ to save quiz data.", code="INVALID_TYPE", status_code=400)

        if not isinstance(quiz_data, dict):
            raise CubixSkillAPIException("Quiz content must be a valid JSON object.", code="INVALID_QUIZ_DATA", status_code=400)

        # Safely unwrap nested quiz wrappers (e.g., content.quizPayload or content.quiz)
        if 'quizPayload' in quiz_data and isinstance(quiz_data['quizPayload'], dict):
            quiz_data = quiz_data['quizPayload']
        elif 'quiz' in quiz_data and isinstance(quiz_data['quiz'], dict):
            quiz_data = quiz_data['quiz']

        title = (quiz_data.get('title') or lesson.title or 'Untitled Quiz').strip()
        instructions = quiz_data.get('instructions') or quiz_data.get('description') or ''

        try:
            passing_score = int(quiz_data.get('passingScore') or quiz_data.get('passing_score') or 70)
        except (ValueError, TypeError):
            raise CubixSkillAPIException("Passing score must be an integer.", code="INVALID_PASSING_SCORE", status_code=400)

        raw_time_limit = quiz_data.get('timeLimitMinutes') or quiz_data.get('time_limit_minutes')
        time_limit_minutes = None
        if raw_time_limit is not None and raw_time_limit != '':
            try:
                time_limit_minutes = int(raw_time_limit)
            except (ValueError, TypeError):
                raise CubixSkillAPIException("Time limit must be an integer.", code="INVALID_TIME_LIMIT", status_code=400)

        raw_max_attempts = quiz_data.get('maxAttempts') or quiz_data.get('max_attempts')
        max_attempts = None
        if raw_max_attempts is not None and raw_max_attempts != '':
            try:
                max_attempts = int(raw_max_attempts)
            except (ValueError, TypeError):
                raise CubixSkillAPIException("Max attempts must be an integer.", code="INVALID_MAX_ATTEMPTS", status_code=400)

        shuffle_q = quiz_data.get('shuffleQuestions')
        if shuffle_q is None:
            shuffle_q = quiz_data.get('shuffle_questions', False)

        show_res = quiz_data.get('showResult')
        if show_res is None:
            show_res = quiz_data.get('show_result', True)

        quiz, _ = Quiz.objects.update_or_create(
            lesson=lesson,
            defaults={
                'title': title,
                'instructions': instructions,
                'passing_score': passing_score,
                'time_limit_minutes': time_limit_minutes,
                'max_attempts': max_attempts,
                'shuffle_questions': bool(shuffle_q),
                'show_result': bool(show_res),
            }
        )

        questions = quiz_data.get('questions')
        if questions is not None:
            if not isinstance(questions, list):
                raise CubixSkillAPIException("Quiz questions must be a list.", code="INVALID_QUESTIONS_FORMAT", status_code=400)

            quiz.questions.all().delete()

            for idx, q in enumerate(questions):
                if not isinstance(q, dict):
                    raise CubixSkillAPIException(f"Question #{idx + 1} must be an object.", code="INVALID_QUESTION", status_code=400)

                q_text = (q.get('questionText') or q.get('question_text') or q.get('question') or '').strip()
                if not q_text:
                    raise CubixSkillAPIException(f"Question #{idx + 1} text is required.", code="MISSING_QUESTION_TEXT", status_code=400)

                raw_type = str(q.get('questionType') or q.get('question_type') or q.get('type') or 'SINGLE_CHOICE').upper()
                if raw_type not in QuestionType.values:
                    raise CubixSkillAPIException(f"Question #{idx + 1} type '{raw_type}' is not supported.", code="INVALID_QUESTION_TYPE", status_code=400)

                points = q.get('points', 1)
                try:
                    points = int(points)
                except (ValueError, TypeError):
                    raise CubixSkillAPIException(f"Question #{idx + 1} points must be an integer.", code="INVALID_POINTS", status_code=400)

                answer_text = str(q.get('answerText') or q.get('answer_text') or q.get('correctAnswer') or '').strip()

                question = Question.objects.create(
                    quiz=quiz,
                    question_type=raw_type,
                    question_text=q_text,
                    explanation=q.get('explanation', ''),
                    points=points,
                    required=q.get('required', True),
                    answer_text=answer_text,
                    order_index=idx + 1
                )

                opts = q.get('options')
                if raw_type in [QuestionType.SINGLE_CHOICE, QuestionType.MULTIPLE_CHOICE, QuestionType.MULTIPLE_SELECT, QuestionType.TRUE_FALSE]:
                    if not isinstance(opts, list) or len(opts) < 2:
                        raise CubixSkillAPIException(f"Question #{idx + 1} requires at least 2 options.", code="MIN_OPTIONS_REQUIRED", status_code=400)

                    correct_ans = q.get('correctAnswers') or q.get('correctAnswer') or q.get('correct_answer') or []
                    if isinstance(correct_ans, (str, int)):
                        correct_ans_list = [str(correct_ans)]
                    elif isinstance(correct_ans, list):
                        correct_ans_list = [str(ca) for ca in correct_ans]
                    else:
                        correct_ans_list = []

                    has_correct = False
                    for opt_idx, opt in enumerate(opts):
                        if isinstance(opt, str):
                            opt_text = opt.strip()
                            opt_id = ''
                            is_corr = False
                        elif isinstance(opt, dict):
                            opt_text = (opt.get('optionText') or opt.get('option_text') or opt.get('text') or '').strip()
                            opt_id = str(opt.get('id') or '')
                            opt_is_corr = opt.get('isCorrect')
                            if opt_is_corr is None:
                                opt_is_corr = opt.get('is_correct')
                            is_corr = bool(opt_is_corr) if opt_is_corr is not None else False
                        else:
                            raise CubixSkillAPIException(f"Question #{idx + 1} option #{opt_idx + 1} is invalid.", code="INVALID_OPTION", status_code=400)

                        if not opt_text:
                            raise CubixSkillAPIException(f"Question #{idx + 1} option #{opt_idx + 1} text is required.", code="MISSING_OPTION_TEXT", status_code=400)

                        if not is_corr and correct_ans_list:
                            if opt_id and opt_id in correct_ans_list or opt_text and opt_text in correct_ans_list:
                                is_corr = True

                        if is_corr:
                            has_correct = True

                        QuestionOption.objects.create(
                            question=question,
                            option_text=opt_text,
                            is_correct=is_corr,
                            order_index=opt_idx + 1
                        )

                    if not has_correct:
                        raise CubixSkillAPIException(f"Question #{idx + 1} must have a correct answer selected.", code="MISSING_CORRECT_ANSWER", status_code=400)

        return quiz

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
        if lesson.lesson_type not in [LessonType.ASSIGNMENT, LessonType.PROJECT]:
            raise CubixSkillAPIException("Lesson type must be ASSIGNMENT or PROJECT to create an assignment/project.", code="INVALID_TYPE")

        return Assignment.objects.create(
            lesson=lesson,
            title=title,
            instructions=instructions,
            due_date=due_date,
            max_marks=max_marks
        )

    @staticmethod
    @transaction.atomic
    def save_assignment_data(lesson: Lesson, assignment_data: dict) -> Assignment:
        if lesson.lesson_type not in [LessonType.ASSIGNMENT, LessonType.PROJECT]:
            raise CubixSkillAPIException("Lesson type must be ASSIGNMENT or PROJECT to save assignment data.", code="INVALID_TYPE", status_code=400)

        if not isinstance(assignment_data, dict):
            raise CubixSkillAPIException("Assignment content must be a valid JSON object.", code="INVALID_ASSIGNMENT_DATA", status_code=400)

        # Safely unwrap nested assignment wrappers (e.g., content.assignmentPayload or content.assignment)
        if 'assignmentPayload' in assignment_data and isinstance(assignment_data['assignmentPayload'], dict):
            assignment_data = assignment_data['assignmentPayload']
        elif 'assignment' in assignment_data and isinstance(assignment_data['assignment'], dict):
            assignment_data = assignment_data['assignment']

        title = (assignment_data.get('title') or lesson.title or 'Untitled Assignment').strip()
        instructions = (assignment_data.get('instructions') or assignment_data.get('description') or lesson.description or '').strip()

        due_date = assignment_data.get('due_date') or assignment_data.get('dueDate') or None
        if due_date == '':
            due_date = None

        raw_due_days = assignment_data.get('due_days') if 'due_days' in assignment_data else assignment_data.get('dueDays')
        due_days = None
        if raw_due_days is not None and raw_due_days != "":
            try:
                due_days = int(raw_due_days)
                if due_days < 1:
                    raise CubixSkillAPIException("Due Day must be at least 1.", code="INVALID_DUE_DAYS", status_code=400)
            except (ValueError, TypeError):
                raise CubixSkillAPIException("Enter a whole number of days.", code="INVALID_DUE_DAYS", status_code=400)

        max_marks = assignment_data.get('max_marks') or assignment_data.get('maxMarks') or assignment_data.get('maxScore') or 100
        try:
            max_marks = int(max_marks)
        except (ValueError, TypeError):
            max_marks = 100

        allow_text = assignment_data.get('allow_text_submission', assignment_data.get('allowTextSubmission', True))
        allow_file = assignment_data.get('allow_file_submission', assignment_data.get('allowFileSubmission', True))
        allow_url = assignment_data.get('allow_url_submission', assignment_data.get('allowUrlSubmission', False))

        assignment, _ = Assignment.objects.update_or_create(
            lesson=lesson,
            defaults={
                'title': title,
                'instructions': instructions,
                'due_date': due_date,
                'due_days': due_days,
                'max_marks': max_marks,
                'allow_text_submission': bool(allow_text),
                'allow_file_submission': bool(allow_file),
                'allow_url_submission': bool(allow_url),
            }
        )

        assets = assignment_data.get('assets')
        if assets is not None:
            if not isinstance(assets, list):
                raise CubixSkillAPIException("Assignment assets must be a list.", code="INVALID_ASSETS_FORMAT", status_code=400)

            assignment.assets.all().delete()

            for idx, asset in enumerate(assets):
                if not isinstance(asset, dict):
                    continue
                media_file_id = asset.get('media_file_id') or asset.get('mediaFileId') or asset.get('media_id') or asset.get('id')
                if not media_file_id:
                    continue

                try:
                    media_file = MediaFile.objects.get(id=media_file_id)
                except MediaFile.DoesNotExist:
                    raise CubixSkillAPIException(f"MediaFile '{media_file_id}' not found.", code="NOT_FOUND", status_code=404)

                asset_title = (asset.get('title') or media_file.original_filename or f"Attachment #{idx + 1}").strip()
                asset_type = (asset.get('asset_type') or asset.get('assetType') or 'DOCUMENT').upper()

                AssignmentAsset.objects.create(
                    assignment=assignment,
                    media_file=media_file,
                    asset_type=asset_type,
                    title=asset_title,
                    description=asset.get('description', ''),
                    order_index=idx + 1
                )

        return assignment

    @staticmethod
    @transaction.atomic
    def save_resources_data(lesson: Lesson, resources_data: list) -> list:
        if not isinstance(resources_data, list):
            raise CubixSkillAPIException("Resources must be a list of objects.", code="INVALID_RESOURCES_FORMAT", status_code=400)

        lesson.resources.all().delete()

        created_resources = []
        for idx, res in enumerate(resources_data):
            if not isinstance(res, dict):
                raise CubixSkillAPIException(f"Resource item #{idx + 1} must be an object.", code="INVALID_RESOURCE_ITEM", status_code=400)

            media_file_id = res.get('media_file_id') or res.get('mediaFileId') or res.get('media_id') or res.get('media_file')
            url = (res.get('url') or res.get('file_url') or res.get('fileUrl') or '').strip()

            if not media_file_id and not url:
                raise CubixSkillAPIException(f"Resource item #{idx + 1} ('{res.get('title', 'Untitled')}') requires a MediaFile or URL.", code="RESOURCE_MEDIA_OR_URL_REQUIRED", status_code=400)

            media_file = None
            if media_file_id:
                try:
                    media_file = MediaFile.objects.get(id=media_file_id)
                except (MediaFile.DoesNotExist, ValueError, TypeError):
                    raise CubixSkillAPIException(f"MediaFile '{media_file_id}' for resource #{idx + 1} not found.", code="NOT_FOUND", status_code=404)

                if lesson.module and lesson.module.course and lesson.module.course.academy:
                    if media_file.academy_uuid and media_file.academy_uuid != lesson.module.course.academy.id:
                        raise CubixSkillAPIException("Permission denied: Cannot attach resource media from another Academy.", code="CROSS_ACADEMY_MEDIA_FORBIDDEN", status_code=403)

            title = (res.get('title') or (media_file.original_filename if media_file else url) or f"Resource #{idx + 1}").strip()
            description = (res.get('description') or '').strip()
            resource_type = (res.get('resource_type') or res.get('resourceType') or res.get('asset_type') or 'document').lower()
            allow_download = res.get('allow_download', res.get('allowDownload', True))

            resource_obj = LessonResource.objects.create(
                lesson=lesson,
                media_file=media_file,
                title=title,
                url=url,
                description=description,
                resource_type=resource_type,
                allow_download=bool(allow_download),
                order_index=idx + 1
            )
            created_resources.append(resource_obj)

        return created_resources
