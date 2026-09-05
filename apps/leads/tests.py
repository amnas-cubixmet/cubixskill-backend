from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import ValidationError, PermissionDenied

from academy.models import Academy
from users_roles.models import User, SystemRoleCode
from courses.models import Course, CourseStatus
from enrollments.models import Enrollment
from students.models import StudentProfile
from leads.models import (
    Lead,
    LeadCourseInterest,
    LeadAssignment,
    LeadFollowUp,
    LeadNote,
    LeadActivity,
    LeadStatus,
    LeadPriority,
    FollowUpStatus,
    FollowUpType,
)
from leads.services import (
    LeadService,
    LeadDuplicateService,
    LeadAssignmentService,
    LeadFollowUpService,
    LeadStatusService,
    LeadConversionService,
    LeadNoteService,
)
from leads.selectors import LeadSelector
from leads.tasks import check_lead_follow_up_reminders

class LeadsTestCase(TestCase):

    def setUp(self):
        self.client = APIClient()

        # Academies
        self.academy_a = Academy.objects.create(name="Python Academy", slug="python-academy")
        self.academy_b = Academy.objects.create(name="Design Academy", slug="design-academy")

        from credits.models import CreditAccount
        CreditAccount.objects.create(academy=self.academy_a, balance=Decimal('1000.00'))

        # Staff Users
        self.staff_a = User.objects.create_user(
            email="staff_a@python.com",
            password="Password123!",
            full_name="Staff Alpha",
            role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy_a,
            is_staff=True
        )
        self.staff_b = User.objects.create_user(
            email="staff_b@design.com",
            password="Password123!",
            full_name="Staff Beta",
            role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy_b,
            is_staff=True
        )

        # Courses
        self.course_a1 = Course.objects.create(
            academy=self.academy_a,
            title="Python Masterclass",
            slug="python-masterclass",
            status=CourseStatus.PUBLISHED
        )
        self.course_a2 = Course.objects.create(
            academy=self.academy_a,
            title="Django Pro",
            slug="django-pro",
            status=CourseStatus.PUBLISHED
        )
        self.course_b1 = Course.objects.create(
            academy=self.academy_b,
            title="UI/UX Fundamentals",
            slug="ui-ux-fundamentals",
            status=CourseStatus.PUBLISHED
        )

    def test_public_enquiry_creation_and_duplicate_deduplication(self):
        url = f"/api/v1/leads/public/academies/{self.academy_a.slug}/enquiries/"

        # 1. Public enquiry creates new Lead
        payload1 = {
            "full_name": "Rahul Sharma",
            "email": "rahul@example.com",
            "phone": "+91 98765 43210",
            "course_id": str(self.course_a1.id),
            "message": "Interested in Python course",
            "utm_source": "google"
        }
        resp1 = self.client.post(url, payload1, format='json')
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)

        lead = Lead.objects.get(academy=self.academy_a, email_normalized="rahul@example.com")
        self.assertEqual(lead.full_name, "Rahul Sharma")
        self.assertEqual(lead.phone_normalized, "+919876543210")
        self.assertEqual(lead.course_interests.count(), 1)
        self.assertEqual(lead.course_interests.first().course, self.course_a1)

        # 2. Second public enquiry with formatted phone duplicates to SAME Lead
        payload2 = {
            "full_name": "Rahul Sharma",
            "phone": "9876543210",
            "course_id": str(self.course_a2.id),
            "message": "Also interested in Django"
        }
        resp2 = self.client.post(url, payload2, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)

        # Still only 1 Lead record in Academy A
        self.assertEqual(Lead.objects.filter(academy=self.academy_a).count(), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.course_interests.count(), 2)
        self.assertEqual(lead.activities.count(), 2)

        # 3. Public enquiry with cross-academy course ID fails validation
        payload_invalid = {
            "full_name": "Hacker Lead",
            "email": "hacker@example.com",
            "course_id": str(self.course_b1.id)
        }
        resp_invalid = self.client.post(url, payload_invalid, format='json')
        self.assertEqual(resp_invalid.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lead_pipeline_status_transitions(self):
        lead, _ = LeadService.create_or_update_lead(
            academy=self.academy_a,
            full_name="Priya Patel",
            email="priya@example.com",
            created_by=self.staff_a
        )
        self.assertEqual(lead.status, LeadStatus.NEW)

        # NEW -> CONTACTED
        LeadStatusService.transition_status(lead, LeadStatus.CONTACTED, performed_by=self.staff_a)
        lead.refresh_from_db()
        self.assertEqual(lead.status, LeadStatus.CONTACTED)

        # CONTACTED -> LOST requires lost_reason
        with self.assertRaises(ValidationError):
            LeadStatusService.transition_status(lead, LeadStatus.LOST, performed_by=self.staff_a)

        LeadStatusService.transition_status(lead, LeadStatus.LOST, performed_by=self.staff_a, lost_reason="Selected another institute")
        lead.refresh_from_db()
        self.assertEqual(lead.status, LeadStatus.LOST)
        self.assertEqual(lead.lost_reason, "Selected another institute")

        # LOST -> INTERESTED (Reopened)
        LeadStatusService.transition_status(lead, LeadStatus.INTERESTED, performed_by=self.staff_a)
        lead.refresh_from_db()
        self.assertEqual(lead.status, LeadStatus.INTERESTED)
        self.assertTrue(lead.activities.filter(activity_type='REOPENED').exists())

    def test_lead_assignment_history_and_notification(self):
        lead, _ = LeadService.create_or_update_lead(
            academy=self.academy_a,
            full_name="Amit Verma",
            email="amit@example.com"
        )

        # Assigning to staff outside Academy A fails
        with self.assertRaises(PermissionDenied):
            LeadAssignmentService.assign_lead(lead, self.staff_b, assigned_by_user=self.staff_a)

        # Assigning to staff_a in Academy A succeeds
        assignment = LeadAssignmentService.assign_lead(lead, self.staff_a, assigned_by_user=self.staff_a, reason="Initial sales call")
        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to, self.staff_a)
        self.assertEqual(lead.assignments.count(), 1)
        self.assertIsNone(assignment.unassigned_at)

    def test_follow_up_scheduling_completion_and_reminders(self):
        lead, _ = LeadService.create_or_update_lead(
            academy=self.academy_a,
            full_name="Neha Gupta",
            email="neha@example.com"
        )

        now = timezone.now()
        scheduled_time = now + timedelta(minutes=10)

        # Schedule follow-up
        fu = LeadFollowUpService.schedule_follow_up(
            lead=lead,
            scheduled_at=scheduled_time,
            follow_up_type=FollowUpType.CALL,
            assigned_to=self.staff_a,
            created_by=self.staff_a,
            notes="Discuss course syllabus"
        )
        lead.refresh_from_db()
        self.assertEqual(lead.next_follow_up_at, scheduled_time)

        # Run Celery Beat reminder task
        reminder_res = check_lead_follow_up_reminders()
        self.assertIn("Processed 1 follow-up reminders", reminder_res)

        # Complete follow-up
        LeadFollowUpService.complete_follow_up(
            follow_up=fu,
            outcome="Very interested, wants demo session",
            notes="Completed demo call",
            completed_by=self.staff_a
        )
        fu.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(fu.status, FollowUpStatus.COMPLETED)
        self.assertIsNotNone(lead.last_contacted_at)
        self.assertIsNone(lead.next_follow_up_at)

    def test_lead_conversion_to_student_and_enrollment(self):
        lead, _ = LeadService.create_or_update_lead(
            academy=self.academy_a,
            full_name="Karan Johar",
            email="karan@example.com",
            phone="+91 99999 88888",
            course=self.course_a1
        )

        user, student_profile, enrollment = LeadConversionService.convert_to_student(
            lead=lead,
            course=self.course_a1,
            converted_by=self.staff_a,
            create_enrollment=True
        )

        lead.refresh_from_db()
        self.assertEqual(lead.status, LeadStatus.CONVERTED)
        self.assertEqual(lead.converted_user, user)
        self.assertEqual(lead.converted_student, student_profile)
        self.assertIsNotNone(lead.converted_at)

        self.assertEqual(user.email, "karan@example.com")
        self.assertEqual(user.role_code, SystemRoleCode.STUDENT)
        self.assertFalse(user.password_setup_completed) # Password setup flow preserved

        self.assertIsNotNone(enrollment)
        self.assertEqual(enrollment.student, user)
        self.assertEqual(enrollment.course, self.course_a1)

        # Idempotent conversion check
        user2, student2, enrollment2 = LeadConversionService.convert_to_student(lead)
        self.assertEqual(user2, user)
        self.assertEqual(student2, student_profile)
        self.assertIsNone(enrollment2)

    def test_lead_notes_and_activity_timeline(self):
        lead, _ = LeadService.create_or_update_lead(
            academy=self.academy_a,
            full_name="Siddharth Malhotra",
            email="sid@example.com"
        )

        note = LeadNoteService.add_note(
            lead=lead,
            author=self.staff_a,
            content="Student requested weekend batch discount.",
            is_pinned=True
        )

        timeline = LeadSelector.get_lead_timeline(lead)
        self.assertGreaterEqual(len(timeline), 2)
        note_events = [e for e in timeline if e['type'] == 'NOTE']
        self.assertEqual(len(note_events), 1)
        self.assertEqual(note_events[0]['content'], "Student requested weekend batch discount.")

    def test_lead_dashboard_metrics_and_rest_api(self):
        LeadService.create_or_update_lead(self.academy_a, "Lead 1", email="l1@example.com")
        LeadService.create_or_update_lead(self.academy_a, "Lead 2", email="l2@example.com")

        metrics = LeadSelector.get_dashboard_metrics(self.academy_a)
        self.assertEqual(metrics['total_leads'], 2)
        self.assertEqual(metrics['new_leads'], 2)

        # REST API list
        self.client.force_authenticate(user=self.staff_a)
        resp = self.client.get("/api/v1/leads/leads/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        res_data = resp.json()
        results = res_data['results'] if isinstance(res_data, dict) and 'results' in res_data else res_data
        self.assertEqual(len(results), 2)

    def test_demo_lead_creation_and_access_control(self):
        # 1. Unauthenticated request rejected
        unauth_resp = self.client.post("/api/v1/demo-leads/demo-leads/", {
            "academy_id": str(self.academy_a.id),
            "course_id": str(self.course_a1.id),
        })
        self.assertEqual(unauth_resp.status_code, status.HTTP_401_UNAUTHORIZED)

        # 2. Authenticated Student request creates Demo Lead with user snapshot
        student_user = User.objects.create_user(
            email="student_demo@example.com",
            password="Password123!",
            full_name="Demo Student",
            role_code=SystemRoleCode.STUDENT
        )
        self.client.force_authenticate(user=student_user)

        auth_resp = self.client.post("/api/v1/demo-leads/demo-leads/", {
            "academy_id": str(self.academy_a.id),
            "course_id": str(self.course_a1.id),
            "phone": "+919876543210",
            "message": "Interested in demo session"
        })
        self.assertEqual(auth_resp.status_code, status.HTTP_201_CREATED)
        res_data = auth_resp.json()
        self.assertEqual(res_data['phone'], "+919876543210")
        self.assertEqual(res_data['student']['email'], "student_demo@example.com")
        self.assertEqual(res_data['status'], "NEW")

        # 3. Reject cross-academy course mapping
        cross_resp = self.client.post("/api/v1/demo-leads/demo-leads/", {
            "academy_id": str(self.academy_b.id),
            "course_id": str(self.course_a1.id),
        })
        self.assertEqual(cross_resp.status_code, status.HTTP_400_BAD_REQUEST)
