from academy.views import AcademyProfileView, AcademySettingsView, AcademyViewSet
from django.urls import include, path
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'academies', AcademyViewSet, basename='academy')

urlpatterns = [
    path('profile/', AcademyProfileView.as_view(), name='academy-profile'),
    path('settings/', AcademySettingsView.as_view(), name='academy-settings'),
    path('', include(router.urls)),
]

