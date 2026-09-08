from enrollments.views import EnrollmentViewSet, StudentEnrollmentViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'enrollments', EnrollmentViewSet, basename='enrollment')
router.register(r'student/enrollments', StudentEnrollmentViewSet, basename='student-enrollment')

urlpatterns = router.urls
