import uuid

from academy.models import Academy
from certificates.generator import CertificatePDFGenerator
from certificates.models import Certificate, CertificateTemplate
from certificates.services import CertificateService
from courses.models import Course
from credits.models import CreditSourceType
from credits.services import CreditsService
from django.contrib.auth import get_user_model
from django.test import TestCase
from enrollments.models import Enrollment
from learning_progress.models import CourseProgress, ProgressStatus
from rest_framework import status
from rest_framework.test import APIClient
from students.models import (
    StudentCustomFieldValue,
    StudentProfile,
)

User = get_user_model()

class EnrollmentCertificateProfileDetailsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.academy = Academy.objects.create(name="Cert Test Academy", slug="cert-test-academy")
        CreditsService.credit(
            academy=self.academy,
            amount=100.0,
            source_type=CreditSourceType.PURCHASE,
            description="Test initial balance",
            idempotency_key=f"test-init-balance-{self.academy.id}"
        )
        
        self.student_user = User.objects.create_user(
            email="cert_student@example.com",
            password="Password123!",
            full_name="Muhammed Ashraf",
            phone="+919876543210",
            academy=self.academy
        )
        self.student_profile, _ = StudentProfile.objects.get_or_create(
            user=self.student_user,
            defaults={'display_name': "Muhammed Ashraf"}
        )

        self.other_user = User.objects.create_user(
            email="other_student@example.com",
            password="Password123!",
            full_name="Other Student",
            academy=self.academy
        )

        self.course = Course.objects.create(
            title="Cert Test Course",
            academy=self.academy,
            certificate_enabled=True
        )

        self.enrollment = Enrollment.objects.create(
            student=self.student_user,
            course=self.course
        )

        self.template = CertificateTemplate.objects.create(
            academy=self.academy,
            name="Default Test Template",
            template_data={"elements": []},
            is_default=True,
            is_active=True
        )

        self.cert_name_def = CertificateService.ensure_certificate_name_field(self.academy)


    def test_unauthenticated_get_returns_401(self):
        url = f"/api/v1/certificates/enrollments/{self.enrollment.id}/profile-details/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_other_student_enrollment_returns_404(self):
        self.client.force_authenticate(user=self.other_user)
        url = f"/api/v1/certificates/enrollments/{self.enrollment.id}/profile-details/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_profile_full_name_exists_but_certificate_name_empty_returns_profile_incomplete(self):
        self.client.force_authenticate(user=self.student_user)
        url = f"/api/v1/certificates/enrollments/{self.enrollment.id}/profile-details/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["certificate_status"], "PROFILE_INCOMPLETE")

        missing_keys = [m["key"] for m in data["missing_fields"]]
        self.assertIn("student.custom.certificate_name", missing_keys)

        fields = {f["key"]: f for f in data["fields"]}
        self.assertIn("student.custom.certificate_name", fields)
        self.assertEqual(fields["student.custom.certificate_name"]["value"], "")
        self.assertTrue(fields["student.custom.certificate_name"]["missing"])

    def test_save_certificate_name_custom_field_and_issue_certificate(self):
        self.client.force_authenticate(user=self.student_user)

        # Mark course progress complete
        CourseProgress.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            status=ProgressStatus.COMPLETED,
            progress_percent=100.0
        )

        url = f"/api/v1/certificates/enrollments/{self.enrollment.id}/profile-details/"
        payload = {
            "values": {
                "student.custom.certificate_name": "MUHAMMED ASHRAF A"
            }
        }
        patch_res = self.client.patch(url, payload, format="json")
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)

        # Confirm User.full_name is UNCHANGED
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.full_name, "Muhammed Ashraf")

        # Confirm custom field value is saved
        val = StudentCustomFieldValue.objects.get(student=self.student_profile, field_definition=self.cert_name_def)
        self.assertEqual(val.value, "MUHAMMED ASHRAF A")

        # Issue certificate
        issue_url = f"/api/v1/certificates/enrollments/{self.enrollment.id}/issue-or-check/"
        issue_res = self.client.post(issue_url, format="json")
        self.assertEqual(issue_res.status_code, status.HTTP_200_OK)
        self.assertTrue(issue_res.json()["success"])

        cert = Certificate.objects.get(enrollment=self.enrollment)
        self.assertEqual(cert.student_name_snapshot, "MUHAMMED ASHRAF A")
        self.assertEqual(cert.custom_data_snapshot.get("student.custom.certificate_name"), "MUHAMMED ASHRAF A")

    def test_pdf_bytes_generation_uses_custom_certificate_name(self):
        CourseProgress.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            status=ProgressStatus.COMPLETED,
            progress_percent=100.0
        )
        StudentCustomFieldValue.objects.create(
            student=self.student_profile,
            field_definition=self.cert_name_def,
            value="MUHAMMED ASHRAF A"
        )

        cert = CertificateService.issue_if_eligible(student=self.student_user, course=self.course, enrollment=self.enrollment)
        pdf_bytes = CertificateService.generate_pdf_bytes_for_certificate(cert)
        self.assertGreater(len(pdf_bytes), 100)
        self.assertEqual(cert.student_name_snapshot, "MUHAMMED ASHRAF A")

    def test_changing_user_full_name_after_issuance_does_not_alter_certificate(self):
        CourseProgress.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            status=ProgressStatus.COMPLETED,
            progress_percent=100.0
        )
        StudentCustomFieldValue.objects.create(
            student=self.student_profile,
            field_definition=self.cert_name_def,
            value="MUHAMMED ASHRAF A"
        )

        cert = CertificateService.issue_if_eligible(student=self.student_user, course=self.course, enrollment=self.enrollment)
        
        # Change normal profile name
        self.student_user.full_name = "New Profile Name"
        self.student_user.save()

        cert.refresh_from_db()
        self.assertEqual(cert.student_name_snapshot, "MUHAMMED ASHRAF A")
        self.assertEqual(cert.custom_data_snapshot.get("student.custom.certificate_name"), "MUHAMMED ASHRAF A")

    def test_changing_certificate_custom_name_after_issuance_does_not_alter_old_certificate(self):
        CourseProgress.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            status=ProgressStatus.COMPLETED,
            progress_percent=100.0
        )
        custom_val = StudentCustomFieldValue.objects.create(
            student=self.student_profile,
            field_definition=self.cert_name_def,
            value="MUHAMMED ASHRAF A"
        )

        cert = CertificateService.issue_if_eligible(student=self.student_user, course=self.course, enrollment=self.enrollment)

        # Update custom field value later
        custom_val.value = "Updated Certificate Name"
        custom_val.save()

        cert.refresh_from_db()
        self.assertEqual(cert.student_name_snapshot, "MUHAMMED ASHRAF A")
        self.assertEqual(cert.custom_data_snapshot.get("student.custom.certificate_name"), "MUHAMMED ASHRAF A")

    def test_editing_certificate_name_does_not_modify_user_full_name(self):
        self.client.force_authenticate(user=self.student_user)
        url = f"/api/v1/certificates/enrollments/{self.enrollment.id}/profile-details/"

        payload = {
            "values": {
                "student.custom.certificate_name": "MUHAMMED ASHRAF A"
            }
        }
        res = self.client.patch(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.full_name, "Muhammed Ashraf")

    def test_editing_user_full_name_does_not_modify_certificate_custom_name(self):
        StudentCustomFieldValue.objects.create(
            student=self.student_profile,
            field_definition=self.cert_name_def,
            value="MUHAMMED ASHRAF A"
        )

        self.student_user.full_name = "New Profile Name"
        self.student_user.save()

        custom_val = StudentCustomFieldValue.objects.get(student=self.student_profile, field_definition=self.cert_name_def)
        self.assertEqual(custom_val.value, "MUHAMMED ASHRAF A")

    def test_owner_can_download_pdf_and_returns_application_pdf(self):
        CourseProgress.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            status=ProgressStatus.COMPLETED,
            progress_percent=100.0
        )
        StudentCustomFieldValue.objects.create(
            student=self.student_profile,
            field_definition=self.cert_name_def,
            value="MUHAMMED ASHRAF A"
        )
        cert = CertificateService.issue_if_eligible(student=self.student_user, course=self.course, enrollment=self.enrollment)

        self.client.force_authenticate(user=self.student_user)
        download_url = f"/api/v1/certificates/student/certificates/{cert.id}/download/"
        res = self.client.get(download_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.headers.get("Content-Type"), "application/pdf")
        self.assertIn(f'inline; filename="certificate_{cert.certificate_number}.pdf"', res.headers.get("Content-Disposition", ""))

    def test_other_student_cannot_download_unowned_certificate(self):
        CourseProgress.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            status=ProgressStatus.COMPLETED,
            progress_percent=100.0
        )
        StudentCustomFieldValue.objects.create(
            student=self.student_profile,
            field_definition=self.cert_name_def,
            value="MUHAMMED ASHRAF A"
        )
        cert = CertificateService.issue_if_eligible(student=self.student_user, course=self.course, enrollment=self.enrollment)

        self.client.force_authenticate(user=self.other_user)
        download_url = f"/api/v1/certificates/student/certificates/{cert.id}/download/"
        res = self.client.get(download_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_verification_requires_no_auth_and_returns_safe_data(self):
        CourseProgress.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            status=ProgressStatus.COMPLETED,
            progress_percent=100.0
        )
        StudentCustomFieldValue.objects.create(
            student=self.student_profile,
            field_definition=self.cert_name_def,
            value="MUHAMMED ASHRAF A"
        )
        cert = CertificateService.issue_if_eligible(student=self.student_user, course=self.course, enrollment=self.enrollment)

        # Unauthenticated request
        self.client.force_authenticate(user=None)
        verify_url = f"/api/v1/certificates/certificates/verify/{cert.verification_code}/"
        res = self.client.get(verify_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        data = res.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["student_name"], "MUHAMMED ASHRAF A")
        self.assertEqual(data["certificate_number"], cert.certificate_number)
        self.assertEqual(data["verification_code"], cert.verification_code)

        # Ensure sensitive details are NOT exposed
        self.assertNotIn("email", data)
        self.assertNotIn("phone", data)
        self.assertNotIn("id", data)

    def test_pdf_generator_font_and_center_coordinate_parity(self):
        from certificates.models import CertificateFont, FontSourceChoices
        from storage.models import MediaFile, MediaStatus, MediaType

        media_file = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            uploaded_by_uuid=self.student_user.id,
            original_filename="test_conv.ttf",
            stored_filename="test_conv.ttf",
            storage_key="test_conv.ttf",
            relative_path="test_conv.ttf",
            mime_type="font/ttf",
            size_bytes=1000,
            media_type=MediaType.OTHER,
            status=MediaStatus.ACTIVE
        )

        font_uuid = str(uuid.uuid4())
        CertificateFont.objects.create(
            id=font_uuid,
            academy=self.academy,
            key=f"cubix-font-{font_uuid}",
            name="Test Font Parity",
            family="Test Font Parity",
            format="TTF",
            weight="400",
            style="normal",
            source=FontSourceChoices.ACADEMY,
            media_file=media_file,
            is_active=True,
            is_certificate_safe=True
        )

        template_data = {
            "elements": [
                {
                    "id": "el-name",
                    "binding": "student.custom.certificate_name",
                    "font_id": font_uuid,
                    "font_family": f"cubix-font-{font_uuid}",
                    "font_size": 32,
                    "x": 0.5,
                    "y": 0.5,
                    "width": 0.8,
                    "height": 0.1,
                    "text_align": "center",
                    "color": "#2563EB"
                }
            ]
        }
        snapshot_data = {
            "student.custom.certificate_name": "Muhammed Ashraf Al Farooqi",
            "academy_id": str(self.academy.id)
        }
        pdf_bytes = CertificatePDFGenerator.generate_pdf(
            snapshot_data=snapshot_data,
            template_data=template_data,
            verification_url="http://localhost:5174/verify/certificate/ABC123TEST"
        )
        self.assertTrue(isinstance(pdf_bytes, bytes))
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_invalid_verification_code_returns_safe_404(self):
        self.client.force_authenticate(user=None)
        verify_url = "/api/v1/certificates/certificates/verify/INVALID-CODE-1234/"
        res = self.client.get(verify_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_template_preview_uses_demo_qr_without_creating_certificate_row(self):
        initial_cert_count = Certificate.objects.count()
        pdf_bytes = CertificateService.preview_template(self.template)
        self.assertTrue(isinstance(pdf_bytes, bytes))
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertEqual(Certificate.objects.count(), initial_cert_count)

    def test_public_verification_handles_preview_demo_token(self):
        self.client.force_authenticate(user=None)
        verify_url = "/api/v1/certificates/certificates/verify/PREVIEW-DEMO/"
        res = self.client.get(verify_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertTrue(data["valid"])
        self.assertTrue(data["is_preview"])
        self.assertEqual(data["verification_code"], "PREVIEW-DEMO")

    def test_custom_font_id_priority_and_safe_fallback(self):
        from certificates.models import CertificateFont, FontSourceChoices
        from storage.models import MediaFile, MediaStatus, MediaType

        # 1. Create MediaFile pointing to test_conv.ttf
        ttf_rel = "test_conv.ttf"
        media_file = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            uploaded_by_uuid=self.student_user.id,
            original_filename="test_conv.ttf",
            stored_filename="test_conv.ttf",
            storage_key="test_conv.ttf",
            relative_path=ttf_rel,
            mime_type="font/ttf",
            size_bytes=1000,
            media_type=MediaType.OTHER,
            status=MediaStatus.ACTIVE
        )

        font_id = str(uuid.uuid4())
        font_obj = CertificateFont.objects.create(
            id=font_id,
            academy=self.academy,
            key=f"cubix-font-{font_id}",
            name="Test Font Custom",
            family="Test Font Custom",
            format="TTF",
            weight="400",
            style="normal",
            source=FontSourceChoices.ACADEMY,
            media_file=media_file,
            is_active=True,
            is_certificate_safe=True
        )

        # 2. Test PDF generation where fontId is authoritative over misleading fontFamily
        template_data = {
            "elements": [
                {
                    "id": "el-1",
                    "fontId": font_id,
                    "fontFamily": "Helvetica",
                    "text": "Hello World",
                    "x": 0.1,
                    "y": 0.1,
                    "width": 0.5,
                    "height": 0.1
                }
            ]
        }
        snapshot_data = {"academy_id": str(self.academy.id)}
        pdf_bytes = CertificatePDFGenerator.generate_pdf(snapshot_data=snapshot_data, template_data=template_data)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        # 3. Deactivated font should fall back to default PDF font and succeed
        font_obj.is_active = False
        font_obj.save()
        pdf_bytes_deact = CertificatePDFGenerator.generate_pdf(snapshot_data=snapshot_data, template_data=template_data)
        self.assertTrue(pdf_bytes_deact.startswith(b"%PDF"))

        # 4. Cross-Academy font lookup should fall back to default PDF font and succeed
        other_academy = Academy.objects.create(name="Other Academy", slug="other-acad")
        font_obj.is_active = True
        font_obj.save()

        other_snapshot = {"academy_id": str(other_academy.id)}
        pdf_bytes_cross = CertificatePDFGenerator.generate_pdf(snapshot_data=other_snapshot, template_data=template_data)
        self.assertTrue(pdf_bytes_cross.startswith(b"%PDF"))

    def test_persistent_pdf_regeneration_preserves_identity_and_credits(self):
        from certificates.models import CertificateStatus, CertPDFMode
        initial_balance = self.academy.credits.first().balance if hasattr(self.academy, 'credits') and self.academy.credits.exists() else None

        cert = Certificate.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            template=self.template,
            certificate_number="CS-2026-TESTREGEN",
            verification_code="VERIFY-REGEN-1234",
            student_name_snapshot="Muhammed Ashraf",
            course_name_snapshot="Test Course",
            academy_name_snapshot=self.academy.name,
            custom_data_snapshot={"academy_id": str(self.academy.id)},
            template_snapshot={"template_data": {"elements": []}},
            pdf_storage_mode=CertPDFMode.STORED,
            status=CertificateStatus.ISSUED
        )

        initial_cert_num = cert.certificate_number
        initial_ver_code = cert.verification_code

        new_bytes = CertificateService.regenerate_pdf_from_snapshot(cert)
        self.assertTrue(new_bytes.startswith(b"%PDF"))

        cert.refresh_from_db()
        self.assertEqual(cert.certificate_number, initial_cert_num)
        self.assertEqual(cert.verification_code, initial_ver_code)

    def test_certificate_pdf_font_fallback(self):
        """
        Verify that unsupported/incompatible fonts fall back to safe default PDF font
        and produce a valid 200 PDF byte stream instead of raising 400.
        """
        from certificates.models import (
            CertificateFont,
            CertificateStatus,
            CertPDFMode,
            FontSourceChoices,
        )

        # Create CFF font DB record (simulating incompatible OTF)
        from storage.models import MediaFile, MediaStatus, MediaType
        media_file = MediaFile.objects.create(
            academy_uuid=self.academy.id,
            uploaded_by_uuid=self.student_user.id,
            original_filename="bad_cff.otf",
            stored_filename="bad_cff.otf",
            storage_key="fonts/bad_cff.otf",
            relative_path="fonts/bad_cff.otf",
            mime_type="font/otf",
            size_bytes=1024,
            media_type=MediaType.OTHER,
            status=MediaStatus.ACTIVE
        )

        cff_font = CertificateFont.objects.create(
            academy=self.academy,
            key="cubix-font-bad-cff",
            name="Incompatible CFF Font",
            family="Incompatible CFF Font",
            source=FontSourceChoices.ACADEMY,
            format="OTF",
            outline_type="CFF",
            pdf_compatible=False,
            media_file=media_file,
            is_active=True
        )

        template_data = {
            "elements": [
                {
                    "binding": "student.custom.certificate_name",
                    "font_id": str(cff_font.id),
                    "x": 0.5,
                    "y": 0.5,
                    "font_size": 24
                }
            ]
        }

        # Render PDF with CFF font - should fall back to default PDF font without raising 400
        snapshot_data = {
            "student.custom.certificate_name": "محمد أشرف / Muhammed Ashraf / ashraf",
            "academy_id": str(self.academy.id)
        }
        pdf_bytes = CertificatePDFGenerator.generate_pdf(snapshot_data=snapshot_data, template_data=template_data)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        # Verify downloading certificate with incompatible font returns valid 200 PDF response
        cert = Certificate.objects.create(
            student=self.student_user,
            course=self.course,
            enrollment=self.enrollment,
            template=self.template,
            certificate_number="CS-2026-FALLBACK",
            verification_code="VERIFY-FALLBACK",
            student_name_snapshot="Muhammed Ashraf",
            course_name_snapshot="Test Course",
            academy_name_snapshot=self.academy.name,
            custom_data_snapshot=snapshot_data,
            template_snapshot={"template_data": template_data},
            pdf_storage_mode=CertPDFMode.ON_DEMAND,
            status=CertificateStatus.ISSUED
        )

        self.client.force_authenticate(user=self.student_user)
        response = self.client.get(f"/api/v1/certificates/student/certificates/{cert.id}/download/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

