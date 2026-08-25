from django.urls import path, include
from rest_framework.routers import DefaultRouter
from discussions_chat.views import (
    CourseDiscussionViewSet,
    ChatRoomViewSet,
    CommunicationReportViewSet,
)

router = DefaultRouter()
router.register(r'discussions', CourseDiscussionViewSet, basename='discussion')
router.register(r'rooms', ChatRoomViewSet, basename='chat-room')
router.register(r'reports', CommunicationReportViewSet, basename='communication-report')
router.register(r'chat/rooms', ChatRoomViewSet, basename='chat-room-alias')
router.register(r'chat/reports', CommunicationReportViewSet, basename='communication-report-alias')

urlpatterns = [
    path('courses/<uuid:course_id>/discussions/', CourseDiscussionViewSet.as_view({'get': 'list', 'post': 'create'}), name='course-discussions-list'),
    path('<uuid:pk>/replies/', CourseDiscussionViewSet.as_view({'get': 'replies', 'post': 'replies'}), name='discussion-replies-direct'),
    path('', include(router.urls)),
]
