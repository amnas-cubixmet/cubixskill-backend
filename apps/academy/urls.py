from django.urls import path, include
from rest_framework.routers import DefaultRouter
from academy.views import AcademyViewSet, AcademyProfileView

router = DefaultRouter()
router.register(r'academies', AcademyViewSet, basename='academy')

urlpatterns = [
    path('profile/', AcademyProfileView.as_view(), name='academy-profile'),
    path('', include(router.urls)),
]

