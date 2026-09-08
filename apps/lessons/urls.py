from django.urls import include, path
from lessons.views import (
    AssignmentViewSet,
    LessonResourceViewSet,
    LessonViewSet,
    ModuleLessonViewSet,
    QuestionOptionViewSet,
    QuestionViewSet,
    QuizViewSet,
)
from rest_framework.routers import DefaultRouter

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'modules/(?P<module_id>[^/.]+)/lessons', ModuleLessonViewSet, basename='module-lesson')
router.register(r'resources', LessonResourceViewSet, basename='lesson-resource')
router.register(r'quizzes', QuizViewSet, basename='quiz')
router.register(r'questions', QuestionViewSet, basename='question')
router.register(r'question-options', QuestionOptionViewSet, basename='question-option')
router.register(r'assignments', AssignmentViewSet, basename='assignment')

urlpatterns = [
    path('<uuid:pk>/resources/', LessonViewSet.as_view({'get': 'resources', 'post': 'resources'})),
    path('<uuid:pk>/', LessonViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'})),
    path('', include(router.urls)),
]
