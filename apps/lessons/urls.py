from django.urls import path, include
from rest_framework.routers import DefaultRouter
from lessons.views import (
    ModuleLessonViewSet, QuizViewSet, QuestionViewSet,
    QuestionOptionViewSet, AssignmentViewSet
)

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'modules/(?P<module_id>[^/.]+)/lessons', ModuleLessonViewSet, basename='module-lesson')
router.register(r'quizzes', QuizViewSet, basename='quiz')
router.register(r'questions', QuestionViewSet, basename='question')
router.register(r'question-options', QuestionOptionViewSet, basename='question-option')
router.register(r'assignments', AssignmentViewSet, basename='assignment')

urlpatterns = [
    path('', include(router.urls)),
]
