from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from academy.models import Academy
from users_roles.models import User, SystemRoleCode
from notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    EmailSuppression,
    DeliveryChannel,
    DeliveryStatus,
    NotificationType,
    SuppressionReason,
)
from notifications.services import NotificationService, EmailService

class NotificationsAppTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.academy = Academy.objects.create(name="Notify Academy", slug="notify-academy")
        self.user = User.objects.create_user(
            email="student@notifyacademy.com",
            full_name="Notify Student",
            role_code=SystemRoleCode.STUDENT,
            academy=self.academy
        )

    def test_notify_user_creates_notification_and_delivery(self):
        """
        Tests that notify_user persists in-app notification and queues email delivery asynchronously.
        """
        notification = NotificationService.notify_user(
            recipient=self.user,
            notification_type=NotificationType.LIVE_SESSION_STARTING_SOON,
            title="Live Session Reminder",
            message="Your live class starts in 15 minutes.",
            channels=[DeliveryChannel.IN_APP, DeliveryChannel.EMAIL],
            idempotency_key="idemp_notify_1"
        )

        self.assertIsNotNone(notification)
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.title, "Live Session Reminder")

        # Verify Deliveries
        in_app_deliv = NotificationDelivery.objects.filter(notification=notification, channel=DeliveryChannel.IN_APP).first()
        self.assertIsNotNone(in_app_deliv)
        self.assertEqual(in_app_deliv.status, DeliveryStatus.DELIVERED)

        email_deliv = NotificationDelivery.objects.filter(notification=notification, channel=DeliveryChannel.EMAIL).first()
        self.assertIsNotNone(email_deliv)
        self.assertEqual(email_deliv.status, DeliveryStatus.QUEUED)

    def test_idempotency_key_enforcement(self):
        """
        Tests that reusing idempotency key returns existing notification without duplicate DB rows.
        """
        notif1 = NotificationService.notify_user(
            recipient=self.user,
            notification_type=NotificationType.PAYMENT_SUCCESS,
            title="Payment Received",
            message="Thank you for your payment.",
            idempotency_key="pay_idemp_key_1"
        )

        notif2 = NotificationService.notify_user(
            recipient=self.user,
            notification_type=NotificationType.PAYMENT_SUCCESS,
            title="Payment Received",
            message="Thank you for your payment.",
            idempotency_key="pay_idemp_key_1"
        )

        self.assertEqual(notif1.id, notif2.id)
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 1)

    def test_suppressed_email_handling(self):
        """
        Tests that emails to suppressed addresses are recorded as SUPPRESSED rather than QUEUED.
        """
        EmailSuppression.objects.create(
            email_normalized=self.user.email.lower(),
            reason=SuppressionReason.HARD_BOUNCE
        )

        delivery = EmailService.send_transactional(
            recipient=self.user.email,
            template_code=NotificationType.COURSE_ENROLLED,
            subject="Welcome to Course",
            context={'body': 'Welcome!'},
            user=self.user
        )

        self.assertEqual(delivery.status, DeliveryStatus.SUPPRESSED)

    def test_mark_as_read_and_read_all(self):
        """
        Tests marking single and all notifications read.
        """
        n1 = NotificationService.notify_user(
            recipient=self.user,
            notification_type=NotificationType.CHAT_MENTION,
            title="Chat Mention",
            message="Someone mentioned you."
        )
        n2 = NotificationService.notify_user(
            recipient=self.user,
            notification_type=NotificationType.DISCUSSION_REPLY,
            title="New Reply",
            message="Someone replied to your thread."
        )

        self.assertFalse(n1.is_read)

        NotificationService.mark_as_read(str(n1.id), self.user)
        n1.refresh_from_db()
        self.assertTrue(n1.is_read)

        unread_count = NotificationService.mark_all_as_read(self.user)
        self.assertEqual(unread_count, 1)

    def test_soft_delete_notification(self):
        """
        Tests soft deletion updates deleted_at timestamp.
        """
        n = NotificationService.notify_user(
            recipient=self.user,
            notification_type=NotificationType.CERTIFICATE_ISSUED,
            title="Certificate Ready",
            message="Download your certificate."
        )

        NotificationService.soft_delete_notification(str(n.id), self.user)
        n.refresh_from_db()
        self.assertIsNotNone(n.deleted_at)

    def test_notifications_rest_api_endpoints(self):
        """
        Tests REST endpoints for listing notifications and unread count.
        """
        self.client.force_authenticate(user=self.user)
        NotificationService.notify_user(
            recipient=self.user,
            notification_type=NotificationType.LIVE_SESSION_CREATED,
            title="New Session",
            message="A new session is scheduled."
        )

        url_list = reverse('notification-list')
        res_list = self.client.get(url_list)
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_list.json()['results']), 1)

        url_count = reverse('notification-unread-count')
        res_count = self.client.get(url_count)
        self.assertEqual(res_count.status_code, status.HTTP_200_OK)
        self.assertEqual(res_count.json()['unread_count'], 1)
