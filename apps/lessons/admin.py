from django.contrib import admin
from lessons.models import Lesson, LessonMedia, LessonRichText, Quiz, Question, QuestionOption, Assignment, AssignmentAsset

#--------------------------------------------------------------
# Admin Configuration
#--------------------------------------------------------------

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'module', 'lesson_type', 'duration_minutes', 'is_demo', 'order_index', 'is_active')
    list_filter = ('lesson_type', 'is_demo', 'is_active', 'module__course__academy')
    search_fields = ('title', 'description', 'module__title')
    ordering = ('module', 'order_index')

@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'lesson', 'passing_score', 'time_limit_minutes')
    search_fields = ('title', 'lesson__title')

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('question_text', 'quiz', 'question_type', 'points', 'order_index')
    list_filter = ('question_type', 'required')
    search_fields = ('question_text', 'quiz__title')

@admin.register(QuestionOption)
class QuestionOptionAdmin(admin.ModelAdmin):
    list_display = ('option_text', 'question', 'is_correct', 'order_index')
    list_filter = ('is_correct',)

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'lesson', 'due_date', 'max_marks')
    search_fields = ('title', 'lesson__title')

admin.site.register(LessonMedia)
admin.site.register(LessonRichText)
admin.site.register(AssignmentAsset)
