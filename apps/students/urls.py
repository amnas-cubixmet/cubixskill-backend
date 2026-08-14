from django.urls import path, include
from rest_framework.routers import DefaultRouter
from students.views import (
    StudentViewSet, StudentSelfServiceViewSet, StudentGuardianViewSet,
    StudentDocumentViewSet, StudentNoteViewSet, StudentTagViewSet
)

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'students', StudentViewSet, basename='student')
router.register(r'student-guardians', StudentGuardianViewSet, basename='student-guardian')
router.register(r'student-documents', StudentDocumentViewSet, basename='student-document')
router.register(r'student-notes', StudentNoteViewSet, basename='student-note')
router.register(r'student-tags', StudentTagViewSet, basename='student-tag')

urlpatterns = [
    path('student/profile/', StudentSelfServiceViewSet.as_view({'get': 'profile', 'patch': 'update_profile'}), name='student-self-profile'),
    path('', include(router.urls)),
]
