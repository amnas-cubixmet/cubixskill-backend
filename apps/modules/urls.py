from django.urls import path, include
from rest_framework.routers import DefaultRouter
from modules.views import CourseModuleViewSet
from lessons.views import ModuleLessonViewSet

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'courses/(?P<course_id>[^/.]+)/modules', CourseModuleViewSet, basename='course-module')

urlpatterns = [
    path('<uuid:module_id>/lessons/', ModuleLessonViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('', include(router.urls)),
]
