from datetime import timedelta

from django.utils import timezone
from leads.models import PlatformDemoRequest
from rest_framework import status
from rest_framework.test import APITestCase


class PublicPlatformDemoRequestTests(APITestCase):
    url = '/api/v1/leads/public/platform-demo/'

    def valid_data(self):
        return {
            'full_name': 'Demo Prospect',
            'email': 'prospect@example.com',
            'phone': '+919876543210',
            'country': 'India',
            'academy_name': 'Example Academy',
            'student_count': '1-100',
            'course_count': '1-3',
            'current_platform': 'None / First Academy',
            'main_requirement': 'Course management and live classes',
            'preferred_date': (timezone.localdate() + timedelta(days=2)).isoformat(),
            'preferred_time': '14:00',
            'time_zone': 'IST (UTC+5:30)',
            'message': '',
        }

    def test_anonymous_request_creates_platform_lead(self):
        response = self.client.post(self.url, self.valid_data(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'received')
        self.assertTrue(response.data['id'])
        self.assertEqual(PlatformDemoRequest.objects.count(), 1)

    def test_past_date_is_rejected(self):
        payload = self.valid_data()
        payload['preferred_date'] = (timezone.localdate() - timedelta(days=1)).isoformat()
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PlatformDemoRequest.objects.count(), 0)
