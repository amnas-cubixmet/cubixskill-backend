from courses.views import CourseCategoryViewSet
from django.urls import include, path
from rest_framework.routers import DefaultRouter

cat_router = DefaultRouter()
cat_router.register(r'', CourseCategoryViewSet, basename='course-category-direct')

urlpatterns = [
    path('', include(cat_router.urls)),
]
