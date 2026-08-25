from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import ValidationError

from academy.models import Academy
from users_roles.models import User
from courses.models import Course, CourseStatus
from enrollments.models import Enrollment, EnrollmentStatus
from learning_progress.models import CourseProgress, ProgressStatus
from storage.models import MediaFile, MediaType, MediaStatus

from certificates.models import (
    CertificateTemplate,
    Certificate,
    CertificateIssueLog,
    CertificateSettings,
    CertPDFMode,
    CertificateStatus,
    IssueLogEventType,
    OrientationChoices,
    PhotoShapeChoices,
)
from certificates.services import CertificateService
from certificates.generator import CertificatePDFGenerator

class CertificateAppTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # 1. Create Academy & Staff
        self.academy_a = Academy.objects.create(name="Academy A", slug="academy-a")
        self.staff_a = User.objects.create_user(
            email="staff_a@test.com",
            password="Password123!",
            full_name="Staff A",
            academy=self.academy_a
        )

        self.academy_b = Academy.objects.create(name="Academy B", slug="academy-b")
        self.staff_b = User.objects.create_user(
            email="staff_b@test.com",
            password="Password123!",
            full_name="Staff B",
            academy=self.academy_b
        )

        # 2. Create Student
        self.student = User.objects.create_user(
            email="student@test.com",
            password="Password123!",
            full_name="Jane Doe"
        )

        # 3. Create Course
        self.course_a = Course.objects.create(
            academy=self.academy_a,
            title="Python Masterclass",
            status=CourseStatus.PUBLISHED,
            certificate_enabled=True
        )

        # 4. Create Enrollment & Completed Progress
        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course_a,
            status=EnrollmentStatus.ACTIVE
        )

        self.progress = CourseProgress.objects.create(
            student=self.student,
            course=self.course_a,
            enrollment=self.enrollment,
            progress_percent=100.00,
            status=ProgressStatus.COMPLETED,
            completed_at=timezone.now()
        )

        # 5. Create Default Template
        self.template = CertificateTemplate.objects.create(
            academy=self.academy_a,
            name="Default A4 Landscape Template",
            orientation=OrientationChoices.LANDSCAPE,
            page_size="A4",
            is_default=True,
            is_active=True,
            show_student_photo=False
        )

    def test_certificate_eligibility_validation(self):
        # 1. Test when course.certificate_enabled is False
        self.course_a.certificate_enabled = False
        self.course_a.save()

        with self.assertRaises(ValidationError):
            CertificateService.issue_if_eligible(self.student, self.course_a)

        self.course_a.certificate_enabled = True
        self.course_a.save()

        # 2. Test when progress is NOT completed
        self.progress.status = ProgressStatus.IN_PROGRESS
        self.progress.progress_percent = 50.00
        self.progress.save()

        with self.assertRaises(ValidationError):
            CertificateService.issue_if_eligible(self.student, self.course_a)

    def test_certificate_issuance_and_idempotency(self):
        # 1. Issue certificate cleanly
        cert1 = CertificateService.issue_if_eligible(
            student=self.student,
            course=self.course_a,
            issued_by=self.staff_a
        )

        self.assertIsNotNone(cert1)
        self.assertTrue(cert1.certificate_number.startswith("CS-"))
        self.assertIsNotNone(cert1.verification_code)
        self.assertEqual(cert1.student_name_snapshot, "Jane Doe")
        self.assertEqual(cert1.course_name_snapshot, "Python Masterclass")
        self.assertEqual(cert1.academy_name_snapshot, "Academy A")
        self.assertEqual(cert1.status, CertificateStatus.ISSUED)
        self.assertEqual(cert1.pdf_storage_mode, CertPDFMode.ON_DEMAND)

        # Audit log created
        log = CertificateIssueLog.objects.filter(certificate=cert1, event_type=IssueLogEventType.ISSUED).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.performed_by, self.staff_a)

        # 2. Idempotency test: issuing again for same student + course returns exact same certificate
        cert2 = CertificateService.issue_if_eligible(
            student=self.student,
            course=self.course_a,
            issued_by=self.staff_a
        )
        self.assertEqual(cert1.id, cert2.id)

    def test_pdf_generation_on_demand(self):
        cert = CertificateService.issue_if_eligible(
            student=self.student,
            course=self.course_a,
            issued_by=self.staff_a
        )

        pdf_bytes = CertificateService.generate_pdf_bytes_for_certificate(cert)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_reissue_and_revoke_lifecycle(self):
        cert = CertificateService.issue_if_eligible(
            student=self.student,
            course=self.course_a,
            issued_by=self.staff_a
        )

        # 1. Revoke Certificate
        revoked_cert = CertificateService.revoke_certificate(cert, revoked_by=self.staff_a, reason="Misconduct")
        self.assertEqual(revoked_cert.status, CertificateStatus.REVOKED)
        self.assertEqual(revoked_cert.revocation_reason, "Misconduct")

        rev_log = CertificateIssueLog.objects.filter(certificate=cert, event_type=IssueLogEventType.REVOKED).first()
        self.assertIsNotNone(rev_log)

        # 2. Reissue Certificate
        new_cert = CertificateService.reissue_certificate(
            certificate=cert,
            reissued_by=self.staff_a,
            reason="Corrected name"
        )
        self.assertEqual(cert.status, CertificateStatus.REISSUED)
        self.assertEqual(new_cert.status, CertificateStatus.ISSUED)
        self.assertEqual(new_cert.reissued_from, cert)

    def test_public_verification_endpoint(self):
        cert = CertificateService.issue_if_eligible(
            student=self.student,
            course=self.course_a,
            issued_by=self.staff_a
        )

        url = f"/api/v1/certificates/certificates/verify/{cert.verification_code}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['certificate_number'], cert.certificate_number)
        self.assertEqual(data['student_name'], "Jane Doe")
        self.assertEqual(data['course_name'], "Python Masterclass")
        self.assertEqual(data['academy_name'], "Academy A")
        self.assertEqual(data['status'], "ISSUED")

        # Non-existent code returns 404
        bad_response = self.client.get("/api/v1/certificates/certificates/verify/INVALID-CODE-999/")
        self.assertEqual(bad_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_student_certificates_api(self):
        cert = CertificateService.issue_if_eligible(
            student=self.student,
            course=self.course_a,
            issued_by=self.staff_a
        )

        self.client.force_authenticate(user=self.student)

        # 1. List certificates
        list_url = "/api/v1/certificates/student/certificates/"
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['results']), 1)

        # 2. Download certificate PDF
        download_url = f"/api/v1/certificates/student/certificates/{cert.id}/download/"
        dl_response = self.client.get(download_url)
        self.assertEqual(dl_response.status_code, status.HTTP_200_OK)
        self.assertEqual(dl_response['Content-Type'], 'application/pdf')
        self.assertTrue(dl_response.content.startswith(b'%PDF-'))

    def test_academy_tenant_isolation(self):
        cert = CertificateService.issue_if_eligible(
            student=self.student,
            course=self.course_a,
            issued_by=self.staff_a
        )

        # Staff A can see Academy A's certificates
        self.client.force_authenticate(user=self.staff_a)
        res_a = self.client.get("/api/v1/certificates/certificates/")
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_a.json()['results']), 1)

        # Staff B from Academy B CANNOT see Academy A's certificates
        self.client.force_authenticate(user=self.staff_b)
        res_b = self.client.get("/api/v1/certificates/certificates/")
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_b.json()['results']), 0)

    def test_template_preview_api(self):
        self.client.force_authenticate(user=self.staff_a)
        preview_url = f"/api/v1/certificates/certificate-templates/{self.template.id}/preview/"

        response = self.client.post(preview_url, {
            'sample_student_name': 'Test Student',
            'sample_course_name': 'Test Course'
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))

    def test_custom_page_size_resolution(self):
        from certificates.generator import resolve_page_size
        from reportlab.lib.units import mm, cm, inch

        # 1. 300 x 200 mm Landscape
        w, h = resolve_page_size("CUSTOM", 300, 200, "MM", "LANDSCAPE")
        self.assertAlmostEqual(w, 300 * mm)
        self.assertAlmostEqual(h, 200 * mm)

        # 2. 25 x 18 cm Portrait
        w, h = resolve_page_size("CUSTOM", 25, 18, "CM", "PORTRAIT")
        self.assertAlmostEqual(w, 18 * cm)
        self.assertAlmostEqual(h, 25 * cm)

        # 3. 12 x 8 inch Landscape
        w, h = resolve_page_size("CUSTOM", 12, 8, "INCH", "LANDSCAPE")
        self.assertAlmostEqual(w, 12 * inch)
        self.assertAlmostEqual(h, 8 * inch)

    def test_custom_page_size_serializer_validation(self):
        from certificates.serializers import CertificateTemplateSerializer

        # 1. Valid custom template
        valid_data = {
            'name': 'Custom MM Template',
            'page_size': 'CUSTOM',
            'custom_width': '300.00',
            'custom_height': '200.00',
            'custom_unit': 'MM',
            'orientation': 'LANDSCAPE'
        }
        serializer = CertificateTemplateSerializer(data=valid_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # 2. Missing custom fields when CUSTOM
        invalid_data = {
            'name': 'Incomplete Custom Template',
            'page_size': 'CUSTOM',
            'orientation': 'LANDSCAPE'
        }
        ser_invalid = CertificateTemplateSerializer(data=invalid_data)
        self.assertFalse(ser_invalid.is_valid())
        self.assertIn('custom_width', ser_invalid.errors)
        self.assertIn('custom_height', ser_invalid.errors)
        self.assertIn('custom_unit', ser_invalid.errors)

        # 3. Predefined page size clears custom fields
        predefined_data = {
            'name': 'Predefined Template',
            'page_size': 'A4',
            'custom_width': '300.00',
            'custom_height': '200.00',
            'custom_unit': 'MM',
            'orientation': 'LANDSCAPE'
        }
        ser_pre = CertificateTemplateSerializer(data=predefined_data)
        self.assertTrue(ser_pre.is_valid())
        self.assertIsNone(ser_pre.validated_data['custom_width'])
        self.assertIsNone(ser_pre.validated_data['custom_height'])
        self.assertIsNone(ser_pre.validated_data['custom_unit'])

    def test_custom_page_size_pdf_generation(self):
        custom_template = CertificateTemplate.objects.create(
            academy=self.academy_a,
            name="Custom 300x200 MM Template",
            page_size="CUSTOM",
            custom_width=300,
            custom_height=200,
            custom_unit="MM",
            orientation="LANDSCAPE",
            is_active=True
        )

        cert = CertificateService.issue_if_eligible(
            student=self.student,
            course=self.course_a,
            template=custom_template,
            issued_by=self.staff_a
        )

        self.assertEqual(cert.template_snapshot['page_size'], 'CUSTOM')
        self.assertEqual(cert.template_snapshot['custom_width'], '300')
        self.assertEqual(cert.template_snapshot['custom_unit'], 'MM')

        pdf_bytes = CertificateService.generate_pdf_bytes_for_certificate(cert)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
