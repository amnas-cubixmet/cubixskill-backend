from django.db.models import QuerySet
from notifications.models import Notification, NotificationPreference
from users_roles.models import User

# --------------------------------------------------------------
# Notification Selectors
# Optimized query selectors for user in-app notifications,
# unread counts, and preferences.
# --------------------------------------------------------------

class NotificationSelector:

    @classmethod
    def get_user_notifications(cls, user: User, unread_only: bool = False, academy_id: str = None) -> QuerySet[Notification]:
        """
        Retrieves user notifications excluding soft-deleted items.
        """
        queryset = Notification.objects.filter(
            recipient=user,
            deleted_at__isnull=True
        )

        if academy_id:
            queryset = queryset.filter(academy_id=academy_id)

        if unread_only:
            queryset = queryset.filter(read_at__isnull=True)

        return queryset.order_by('-created_at')

    @classmethod
    def get_unread_count(cls, user: User, academy_id: str = None) -> int:
        """
        Returns count of unread, non-deleted notifications for a user.
        """
        qs = Notification.objects.filter(
            recipient=user,
            read_at__isnull=True,
            deleted_at__isnull=True
        )
        if academy_id:
            qs = qs.filter(academy_id=academy_id)
        return qs.count()

    @classmethod
    def get_user_preferences(cls, user: User) -> list[NotificationPreference]:
        """
        Retrieves user notification preferences across all categories.
        """
        return NotificationPreference.objects.filter(user=user)
