from django.urls import path, include
from rest_framework.routers import DefaultRouter
from audit_logs.views import AuditLogViewSet, AdminAuditLogViewSet

# --------------------------------------------------------------
# Audit Logs URL Router Registration
# Centralized REST API endpoints for Academy and Admin Audit Logs.
# Record actor, target, action, timestamp, and trusted request context.
# Academy-scoped audit data respects tenant isolation.
# --------------------------------------------------------------


router = DefaultRouter()
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')
router.register(r'admin/audit-logs', AdminAuditLogViewSet, basename='admin-audit-log')

urlpatterns = [
    path('', include(router.urls)),
]
