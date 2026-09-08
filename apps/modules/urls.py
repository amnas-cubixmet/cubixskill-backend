from django.urls import include, path
from lessons.views import ModuleLessonViewSet
from modules.views import CourseModuleViewSet
from rest_framework.routers import DefaultRouter

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'courses/(?P<course_id>[^/.]+)/modules', CourseModuleViewSet, basename='course-module')

urlpatterns = [
    path('<uuid:module_id>/lessons/', ModuleLessonViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('', include(router.urls)),
]
