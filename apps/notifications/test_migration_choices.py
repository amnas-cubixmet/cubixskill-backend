from django.test import SimpleTestCase

from notifications.models import Notification, NotificationType


class NotificationChoiceTests(SimpleTestCase):
    def test_announcement_type_is_available(self):
        choices = dict(Notification._meta.get_field('notification_type').choices)
        self.assertIn(NotificationType.ANNOUNCEMENT_PUBLISHED, choices)
