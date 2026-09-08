from decimal import Decimal

from academy.models import Academy
from analytics_reports.models import ReportStatus, ReportType
from analytics_reports.selectors import AnalyticsSelector
from analytics_reports.services import ReportService
from courses.models import Course, CourseStatus
from django.test import TestCase
from django.urls import reverse
from enrollments.models import Enrollment, EnrollmentStatus
from payments.models import OrderStatus, PaymentContext, PaymentOrder
from rest_framework import status
from rest_framework.test import APIClient
from students.models import StudentProfile
from users_roles.models import SystemRoleCode, User

# --------------------------------------------------------------
# Analytics & Reports Unit & Integration Tests
# Validates live domain aggregation selectors, tenant isolation rules,
# asynchronous ReportJob dispatch, and REST API analytics endpoints.
# Analytics aggregates domain data but is not the source of truth;
# Payment, Progress, Leads, and Credits domains remain authoritative.
# --------------------------------------------------------------


class AnalyticsReportsTestCase(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.academy = Academy.objects.create(name="Analytics Academy", slug="analytics-academy")
        self.user = User.objects.create_user(
            email="staff@analyticsacademy.com",
            full_name="Analytics Staff",
            role_code=SystemRoleCode.ACADEMY_STAFF,
            academy=self.academy
        )
        self.student_user = User.objects.create_user(
            email="student@analyticsacademy.com",
            full_name="Analytics Student",
            role_code=SystemRoleCode.STUDENT,
            academy=self.academy
        )
        self.student = StudentProfile.objects.create(
            user=self.student_user,
            student_code="STU_ANALYTICS_001",
            display_name="Analytics Student"
        )
        self.course = Course.objects.create(
            academy=self.academy,
            title="Analytics 101",
            slug="analytics-101",
            status=CourseStatus.PUBLISHED
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student_user,
            course=self.course,
            status=EnrollmentStatus.ACTIVE
        )
        self.payment_order = PaymentOrder.objects.create(
            academy=self.academy,
            payer=self.student_user,
            course=self.course,
            order_number="ORD_ANALYTICS_001",
            payment_context=PaymentContext.COURSE_PURCHASE,
            subtotal_amount=Decimal('1000.00'),
            final_amount=Decimal('1000.00'),
            currency="INR",
            status=OrderStatus.COMPLETED
        )


    def test_academy_dashboard_selector(self):
        """
        Tests calculation of Academy dashboard metrics from domain data.
        """
        dashboard = AnalyticsSelector.get_academy_dashboard(self.academy)
        self.assertEqual(dashboard['total_students'], 1)
        self.assertEqual(dashboard['active_students'], 1)
        self.assertEqual(dashboard['total_courses'], 1)
        self.assertEqual(dashboard['active_enrollments'], 1)
        self.assertEqual(dashboard['revenue_by_currency'].get('INR'), '1000.00')

    def test_course_analytics_selector(self):
        """
        Tests calculation of per-course metrics.
        """
        results = AnalyticsSelector.get_course_analytics(self.academy)
        self.assertEqual(len(results), 1)
        c_stats = results[0]
        self.assertEqual(c_stats['course_title'], "Analytics 101")
        self.assertEqual(c_stats['total_enrollments'], 1)
        self.assertEqual(c_stats['revenue'], '1000.00')

    def test_revenue_analytics_grouped_by_currency(self):
        """
        Tests revenue analytics grouping by currency.
        """
        rev = AnalyticsSelector.get_revenue_analytics(self.academy)
        self.assertIn('INR', rev)
        self.assertEqual(rev['INR']['gross_revenue'], '1000.00')
        self.assertEqual(rev['INR']['net_revenue'], '1000.00')

    def test_report_job_execution(self):
        """
        Tests asynchronous report job creation, file generation, and completion status.
        """
        job = ReportService.create_report_job(
            user=self.user,
            report_type=ReportType.STUDENTS,
            format_type="CSV"
        )
        self.assertEqual(job.status, ReportStatus.PENDING)

        ReportService.generate_report_file(str(job.id))
        job.refresh_from_db()

        self.assertEqual(job.status, ReportStatus.COMPLETED)
        self.assertIsNotNone(job.result_media)
        self.assertTrue(job.result_filename.startswith("report_students_"))

    def test_analytics_rest_api_endpoints(self):
        """
        Tests REST API endpoints for Academy dashboard and report job dispatching.
        """
        self.client.force_authenticate(user=self.user)

        url_dash = reverse('analytics-dashboard')
        res_dash = self.client.get(url_dash)
        self.assertEqual(res_dash.status_code, status.HTTP_200_OK)
        self.assertEqual(res_dash.json()['total_students'], 1)

        url_reports = reverse('report-job-list')
        res_create = self.client.post(url_reports, data={
            'report_type': ReportType.ENROLLMENTS,
            'format': 'CSV'
        }, format='json')
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_create.json()['status'], ReportStatus.PENDING)
