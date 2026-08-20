from django.urls import path, include
from rest_framework.routers import DefaultRouter
from courses.views import CourseViewSet, CourseCategoryViewSet, CourseModuleViewSet, CourseLanguageViewSet

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'courses', CourseViewSet, basename='course')
router.register(r'course-categories', CourseCategoryViewSet, basename='course-category')
router.register(r'course-languages', CourseLanguageViewSet, basename='course-language')
router.register(r'course-modules', CourseModuleViewSet, basename='course-module')
router.register(r'', CourseViewSet, basename='course-root')

category_router = DefaultRouter()
category_router.register(r'', CourseCategoryViewSet, basename='course-category-direct')

urlpatterns = [
    path('', include(router.urls)),
    path('direct-categories/', include(category_router.urls)),
]


