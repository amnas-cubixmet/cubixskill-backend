from rest_framework.routers import DefaultRouter
from enrollments.views import EnrollmentViewSet, StudentEnrollmentViewSet

router = DefaultRouter()
router.register(r'enrollments', EnrollmentViewSet, basename='enrollment')
router.register(r'student/enrollments', StudentEnrollmentViewSet, basename='student-enrollment')

urlpatterns = router.urls
