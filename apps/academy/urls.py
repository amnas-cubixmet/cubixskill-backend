from django.urls import path, include
from rest_framework.routers import DefaultRouter
from academy.views import AcademyViewSet, AcademyProfileView, AcademySettingsView

router = DefaultRouter()
router.register(r'academies', AcademyViewSet, basename='academy')

urlpatterns = [
    path('profile/', AcademyProfileView.as_view(), name='academy-profile'),
    path('settings/', AcademySettingsView.as_view(), name='academy-settings'),
    path('', include(router.urls)),
]

