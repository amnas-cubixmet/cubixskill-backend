from django.urls import include, path
from live_classes.views import (
    LiveSessionViewSet,
    StudentLiveClassesView,
)
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'live-sessions', LiveSessionViewSet, basename='live-session')

urlpatterns = [
    path('student/live-classes/', StudentLiveClassesView.as_view(), name='student-live-classes'),
    path('', include(router.urls)),
]
