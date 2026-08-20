from django.urls import path, include
from rest_framework.routers import DefaultRouter
from courses.views import CourseCategoryViewSet

cat_router = DefaultRouter()
cat_router.register(r'', CourseCategoryViewSet, basename='course-category-direct')

urlpatterns = [
    path('', include(cat_router.urls)),
]
