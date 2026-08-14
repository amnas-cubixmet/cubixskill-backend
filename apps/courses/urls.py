from django.urls import path, include
from rest_framework.routers import DefaultRouter
from courses.views import CourseViewSet, CourseCategoryViewSet, CourseModuleViewSet

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'courses', CourseViewSet, basename='course')
router.register(r'course-categories', CourseCategoryViewSet, basename='course-category')
router.register(r'course-modules', CourseModuleViewSet, basename='course-module')

urlpatterns = [
    path('', include(router.urls)),
]
