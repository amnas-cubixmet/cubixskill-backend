from django.urls import path, include
from rest_framework.routers import DefaultRouter
from modules.views import CourseModuleViewSet

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'courses/(?P<course_id>[^/.]+)/modules', CourseModuleViewSet, basename='course-module')

urlpatterns = [
    path('', include(router.urls)),
]
