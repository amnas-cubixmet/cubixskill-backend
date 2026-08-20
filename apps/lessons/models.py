from django.db import models
from core.models import BaseModel, ActiveMixin, OrderMixin
from storage.models import MediaFile

#--------------------------------------------------------------
# Enums
#--------------------------------------------------------------

class LessonType(models.TextChoices):
    VIDEO = 'VIDEO', 'Video'
    AUDIO = 'AUDIO', 'Audio'
    IMAGE = 'IMAGE', 'Image'
    DOCUMENT = 'DOCUMENT', 'Document'
    RICH_TEXT = 'RICH_TEXT', 'Rich Text'
    QUIZ = 'QUIZ', 'Quiz'
    ASSIGNMENT = 'ASSIGNMENT', 'Assignment'
    URL = 'URL', 'External URL'
    PROJECT = 'PROJECT', 'Project'

class MediaRole(models.TextChoices):
    PRIMARY = 'PRIMARY', 'Primary Media'
    ATTACHMENT = 'ATTACHMENT', 'Attachment'
    THUMBNAIL = 'THUMBNAIL', 'Thumbnail'
    RESOURCE = 'RESOURCE', 'Resource'

class QuestionType(models.TextChoices):
    SINGLE_CHOICE = 'SINGLE_CHOICE', 'Single Choice'
    MULTIPLE_CHOICE = 'MULTIPLE_CHOICE', 'Multiple Choice'
    TRUE_FALSE = 'TRUE_FALSE', 'True / False'
    SHORT_ANSWER = 'SHORT_ANSWER', 'Short Answer'
    LONG_ANSWER = 'LONG_ANSWER', 'Long Answer'

class AssetType(models.TextChoices):
    IMAGE = 'IMAGE', 'Image'
    VIDEO = 'VIDEO', 'Video'
    AUDIO = 'AUDIO', 'Audio'
    DOCUMENT = 'DOCUMENT', 'Document'
    RESOURCE = 'RESOURCE', 'Resource'
    STARTER_FILE = 'STARTER_FILE', 'Starter File'

#--------------------------------------------------------------
# 1. Primary Lesson Model
#--------------------------------------------------------------

class Lesson(BaseModel, ActiveMixin, OrderMixin):
    module = models.ForeignKey('modules.Module', on_delete=models.CASCADE, related_name='lessons', null=True, blank=True)
    title = models.CharField(max_length=255)
    lesson_type = models.CharField(max_length=20, choices=LessonType.choices, default=LessonType.VIDEO, db_index=True)
    description = models.TextField(blank=True, default='')

    duration_minutes = models.PositiveIntegerField(default=0)
    is_demo = models.BooleanField(default=False)
    allow_download = models.BooleanField(default=False)
    external_url = models.URLField(blank=True, default='')

    class Meta:
        db_table = 'lessons'
        ordering = ['order_index', 'created_at']

    def __str__(self):
        return f"{self.title} ({self.lesson_type})"

#--------------------------------------------------------------
# 2. Lesson Media Model
#--------------------------------------------------------------

class LessonMedia(BaseModel):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='media_files', null=True, blank=True)
    media_file = models.ForeignKey(MediaFile, on_delete=models.PROTECT, related_name='lesson_media', null=True, blank=True)
    media_role = models.CharField(max_length=20, choices=MediaRole.choices, default=MediaRole.PRIMARY)
    caption = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'lesson_media'

    def __str__(self):
        return f"{self.media_role} for {self.lesson.title}"

#--------------------------------------------------------------
# 3. Lesson Rich Text Model
#--------------------------------------------------------------

class LessonRichText(BaseModel):
    lesson = models.OneToOneField(Lesson, on_delete=models.CASCADE, related_name='rich_text')
    content = models.TextField()

    class Meta:
        db_table = 'lesson_rich_texts'

    def __str__(self):
        return f"Rich Text for {self.lesson.title}"

#--------------------------------------------------------------
# 4. Quiz Model
#--------------------------------------------------------------

class Quiz(BaseModel):
    lesson = models.OneToOneField(Lesson, on_delete=models.CASCADE, related_name='quiz')
    title = models.CharField(max_length=255)
    instructions = models.TextField(blank=True, default='')

    passing_score = models.PositiveIntegerField(default=70)
    time_limit_minutes = models.PositiveIntegerField(null=True, blank=True)
    max_attempts = models.PositiveIntegerField(null=True, blank=True)

    shuffle_questions = models.BooleanField(default=False)
    show_result = models.BooleanField(default=True)

    class Meta:
        db_table = 'quizzes'

    def __str__(self):
        return f"Quiz: {self.title}"

#--------------------------------------------------------------
# 5. Question Model
#--------------------------------------------------------------

class Question(BaseModel, OrderMixin):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions', null=True, blank=True)
    question_type = models.CharField(max_length=30, choices=QuestionType.choices, default=QuestionType.SINGLE_CHOICE)
    question_text = models.TextField()
    explanation = models.TextField(blank=True, default='')
    points = models.PositiveIntegerField(default=1)
    required = models.BooleanField(default=True)
    answer_text = models.TextField(blank=True, default='')  # Short answer support

    class Meta:
        db_table = 'questions'
        ordering = ['order_index', 'created_at']

    def __str__(self):
        return f"Question ({self.question_type}): {self.question_text[:30]}"

#--------------------------------------------------------------
# 6. Question Option Model
#--------------------------------------------------------------

class QuestionOption(BaseModel, OrderMixin):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options', null=True, blank=True)
    option_text = models.CharField(max_length=255)
    is_correct = models.BooleanField(default=False)

    class Meta:
        db_table = 'question_options'
        ordering = ['order_index', 'created_at']

    def __str__(self):
        return f"Option: {self.option_text} (Correct: {self.is_correct})"

#--------------------------------------------------------------
# 7. Assignment Model
#--------------------------------------------------------------

class Assignment(BaseModel):
    lesson = models.OneToOneField(Lesson, on_delete=models.CASCADE, related_name='assignment')
    title = models.CharField(max_length=255)
    instructions = models.TextField()
    due_date = models.DateTimeField(null=True, blank=True)
    max_marks = models.PositiveIntegerField(default=100)

    allow_text_submission = models.BooleanField(default=True)
    allow_file_submission = models.BooleanField(default=True)
    allow_url_submission = models.BooleanField(default=False)

    class Meta:
        db_table = 'assignments'

    def __str__(self):
        return f"Assignment: {self.title}"

#--------------------------------------------------------------
# 8. Assignment Asset Model
#--------------------------------------------------------------

class AssignmentAsset(BaseModel, OrderMixin):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='assets', null=True, blank=True)
    media_file = models.ForeignKey(MediaFile, on_delete=models.PROTECT, related_name='assignment_assets', null=True, blank=True)
    asset_type = models.CharField(max_length=30, choices=AssetType.choices, default=AssetType.DOCUMENT)
    title = models.CharField(max_length=255, blank=True, default='')
    description = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'assignment_assets'
        ordering = ['order_index', 'created_at']

    def __str__(self):
        return f"Asset: {self.title or self.media_file.original_filename}"

#--------------------------------------------------------------
# 9. Lesson Resource Link Model
#--------------------------------------------------------------

class LessonResource(BaseModel, OrderMixin):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='resources')
    media_file = models.ForeignKey(MediaFile, on_delete=models.SET_NULL, related_name='lesson_resources', null=True, blank=True)
    title = models.CharField(max_length=255)
    url = models.URLField(max_length=500, blank=True, default='')
    description = models.TextField(blank=True, default='')
    resource_type = models.CharField(max_length=50, blank=True, default='link')
    allow_download = models.BooleanField(default=False)

    class Meta:
        db_table = 'lesson_resources'
        ordering = ['order_index', 'created_at']

    def __str__(self):
        return f"Resource ({self.title}): {self.url}"
