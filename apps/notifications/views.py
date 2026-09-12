from notifications.models import (
    EmailSuppression,
    NotificationPreference,
    SuppressionReason,
)
from notifications.selectors import NotificationSelector
from notifications.serializers import (
    NotificationPreferenceSerializer,
    NotificationSerializer,
)
from notifications.services import NotificationService
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

# --------------------------------------------------------------
# 1. User In-App Notifications ViewSet
# Provides REST endpoints for fetching notifications, unread counts,
# marking notifications read, and soft-deleting UI items.
# --------------------------------------------------------------

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        academy_id = self.request.query_params.get('academy_id') or self.request.query_params.get('academy_uuid')
        return NotificationSelector.get_user_notifications(
            user=self.request.user,
            unread_only=(self.request.query_params.get('unread_only') == 'true'),
            academy_id=academy_id
        )

    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        academy_id = request.query_params.get('academy_id') or request.query_params.get('academy_uuid')
        count = NotificationSelector.get_unread_count(request.user, academy_id=academy_id)
        return Response({"unread_count": count}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        notification = NotificationService.mark_as_read(
            notification_id=pk,
            user=request.user
        )
        return Response(NotificationSerializer(notification).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='read-all')
    def mark_all_read(self, request):
        academy_id = request.data.get('academy_id') or request.data.get('academy_uuid') or request.query_params.get('academy_id')
        count = NotificationService.mark_all_as_read(user=request.user, academy_id=academy_id)
        return Response({
            "message": f"Marked {count} notifications as read.",
            "updated_count": count
        }, status=status.HTTP_200_OK)

    def destroy(self, request, pk=None):
        notification = NotificationService.soft_delete_notification(
            notification_id=pk,
            user=request.user
        )
        return Response({"message": "Notification removed successfully."}, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 2. Notification Preferences Endpoint
# --------------------------------------------------------------

class NotificationPreferenceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        prefs = NotificationSelector.get_user_preferences(request.user)
        serializer = NotificationPreferenceSerializer(prefs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        notification_type = request.data.get('notification_type')
        if not notification_type:
            raise ValidationError({"notification_type": "Notification type is required."})

        pref, _ = NotificationPreference.objects.get_or_create(
            user=request.user,
            notification_type=notification_type
        )

        if 'in_app_enabled' in request.data:
            pref.in_app_enabled = request.data['in_app_enabled']
        if 'email_enabled' in request.data:
            pref.email_enabled = request.data['email_enabled']
        if 'push_enabled' in request.data:
            pref.push_enabled = request.data['push_enabled']

        pref.save()
        return Response(NotificationPreferenceSerializer(pref).data, status=status.HTTP_200_OK)

# --------------------------------------------------------------
# 3. Email Provider Webhook Endpoint
# Processes hard bounces and spam complaints from email providers.
# Automatically populates EmailSuppression to protect domain reputation.
# --------------------------------------------------------------

class EmailProviderWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, provider):
        payload = request.data
        event_type = payload.get('event') or payload.get('type') or ''
        email = payload.get('email') or payload.get('recipient') or ''

        if email and ('bounce' in event_type.lower() or 'complaint' in event_type.lower()):
            reason = SuppressionReason.COMPLAINT if 'complaint' in event_type.lower() else SuppressionReason.HARD_BOUNCE
            EmailSuppression.objects.get_or_create(
                email_normalized=email.lower(),
                defaults={
                    'reason': reason,
                    'source': f"WEBHOOK_{provider.upper()}"
                }
            )

        return Response({"status": "processed"}, status=status.HTTP_200_OK)
