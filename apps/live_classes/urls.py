from django.urls import path, include
from rest_framework.routers import DefaultRouter
from live_classes.views import (
    LiveSessionViewSet,
    StudentLiveClassesView,
)

router = DefaultRouter()
router.register(r'live-sessions', LiveSessionViewSet, basename='live-session')

urlpatterns = [
    path('student/live-classes/', StudentLiveClassesView.as_view(), name='student-live-classes'),
    path('', include(router.urls)),
]
