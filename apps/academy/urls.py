from django.urls import path, include
from rest_framework.routers import DefaultRouter
from academy.views import AcademyViewSet

#--------------------------------------------------------------
# Router Setup
#--------------------------------------------------------------

router = DefaultRouter()
router.register(r'academies', AcademyViewSet, basename='academy')

urlpatterns = [
    path('', include(router.urls)),
]
