from django.urls import path, include
from rest_framework.routers import DefaultRouter
from control_panel.support_api_views import SupportTicketViewSet

router = DefaultRouter()
router.register(r'tickets', SupportTicketViewSet, basename='support-ticket')

urlpatterns = [
    path('', include(router.urls)),
]
