from django.urls import path, include
from rest_framework.routers import DefaultRouter
from discussions_chat.views import (
    CourseDiscussionViewSet,
    ChatRoomViewSet,
    CommunicationReportViewSet,
)

router = DefaultRouter()
router.register(r'discussions', CourseDiscussionViewSet, basename='discussion')
router.register(r'chat/rooms', ChatRoomViewSet, basename='chat-room')
router.register(r'chat/reports', CommunicationReportViewSet, basename='communication-report')

urlpatterns = [
    path('courses/<uuid:course_id>/discussions/', CourseDiscussionViewSet.as_view({'get': 'list', 'post': 'create'}), name='course-discussions-list'),
    path('', include(router.urls)),
]
