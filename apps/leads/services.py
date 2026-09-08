from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from enrollments.services import EnrollmentService
from leads.models import (
    FollowUpStatus,
    InterestLevel,
    Lead,
    LeadActivity,
    LeadAssignment,
    LeadCourseInterest,
    LeadFollowUp,
    LeadNote,
    LeadStatus,
    normalize_email_address,
    normalize_phone_number,
)
from notifications.services import EmailService
from rest_framework.exceptions import PermissionDenied, ValidationError
from students.models import StudentProfile
from users_roles.models import SystemRoleCode, User

# --------------------------------------------------------------
# 1. Lead Duplicate Service
# Deduplicates Leads strictly within the SAME Academy.
# Duplicate detection is Academy-scoped; the same email/phone may legitimately
# exist as a Lead in another Academy.
# --------------------------------------------------------------

class LeadDuplicateService:

    @classmethod
    def find_duplicate(cls, academy, email: str = "", phone: str = "") -> Lead | None:
        """
        Deduplicates Leads strictly within the SAME Academy.
        Prevents merging cross-academy leads for tenant safety.
        """
        if not academy:
            return None

        norm_email = normalize_email_address(email)
        norm_phone = normalize_phone_number(phone)

        if norm_email:
            existing = Lead.objects.filter(academy=academy, email_normalized=norm_email).first()
            if existing:
                return existing

        if norm_phone:
            last_10 = norm_phone[-10:] if len(norm_phone) >= 10 else norm_phone
            existing = Lead.objects.filter(academy=academy).filter(
                Q(phone_normalized=norm_phone) | Q(phone_normalized__endswith=last_10)
            ).first()
            if existing:
                return existing

        return None

class LeadService:

    @classmethod
    @transaction.atomic
    def create_or_update_lead(
        cls,
        academy,
        full_name: str,
        email: str = "",
        phone: str = "",
        source: str = "WEBSITE",
        source_detail: str = "",
        priority: str = "NORMAL",
        preferred_contact_method: str = "EMAIL",
        course=None,
        metadata: dict = None,
        created_by=None
    ) -> tuple[Lead, bool]:
        """
        Creates a new Lead or safely updates an existing duplicate Lead in the same Academy.
        """
        if not email and not phone:
            raise ValidationError("At least one contact method (email or phone) is required to create a Lead.")

        existing_lead = LeadDuplicateService.find_duplicate(academy, email=email, phone=phone)

        now = timezone.now()

        if existing_lead:
            # Update existing lead details if missing
            if not existing_lead.email and email:
                existing_lead.email = email
            if not existing_lead.phone and phone:
                existing_lead.phone = phone

            if metadata:
                existing_lead.metadata.update(metadata)

            existing_lead.last_contacted_at = now
            existing_lead.save()

            # Add course interest if provided and not already attached
            if course:
                LeadCourseInterest.objects.get_or_create(
                    lead=existing_lead,
                    course=course,
                    defaults={'interest_level': InterestLevel.HIGH}
                )

            LeadActivity.objects.create(
                lead=existing_lead,
                activity_type='ENQUIRY_RECEIVED_DUPLICATE_LEAD',
                performed_by=created_by,
                metadata={'source': source, 'source_detail': source_detail}
            )

            return existing_lead, False

        # Create new Lead
        lead = Lead.objects.create(
            academy=academy,
            full_name=full_name,
            email=email,
            phone=phone,
            source=source,
            source_detail=source_detail,
            priority=priority,
            preferred_contact_method=preferred_contact_method,
            metadata=metadata or {},
            status=LeadStatus.NEW
        )

        if course:
            LeadCourseInterest.objects.create(
                lead=lead,
                course=course,
                interest_level=InterestLevel.HIGH,
                is_primary=True
            )

        LeadActivity.objects.create(
            lead=lead,
            activity_type='LEAD_CREATED',
            performed_by=created_by,
            metadata={'source': source}
        )

        return lead, True

class LeadAssignmentService:

    @classmethod
    @transaction.atomic
    def assign_lead(cls, lead: Lead, assigned_to_user: User, assigned_by_user: User = None, reason: str = "") -> LeadAssignment:
        """
        Assigns a lead to an Academy Staff member and records ownership history.
        """
        if assigned_to_user.academy != lead.academy:
            raise PermissionDenied("Cannot assign a Lead to a staff member outside the Lead's Academy.")

        # Unassign previous active assignment
        now = timezone.now()
        LeadAssignment.objects.filter(lead=lead, unassigned_at__isnull=True).update(unassigned_at=now)

        lead.assigned_to = assigned_to_user
        lead.save(update_fields=['assigned_to'])

        assignment = LeadAssignment.objects.create(
            lead=lead,
            assigned_to=assigned_to_user,
            assigned_by=assigned_by_user,
            reason=reason
        )

        LeadActivity.objects.create(
            lead=lead,
            activity_type='LEAD_ASSIGNED',
            performed_by=assigned_by_user,
            metadata={'assigned_to': assigned_to_user.email}
        )

        # Notify assigned staff member
        if assigned_to_user.email:
            EmailService.send_transactional(
                recipient=assigned_to_user.email,
                template_code="LEAD_ASSIGNED_NOTIFICATION",
                subject=f"New Lead Assigned: {lead.full_name}",
                context={
                    'body': f"You have been assigned lead '{lead.full_name}' ({lead.email or lead.phone}).",
                    'lead_name': lead.full_name,
                },
                user=assigned_to_user,
                academy=lead.academy
            )

        return assignment

class LeadFollowUpService:

    @classmethod
    @transaction.atomic
    def schedule_follow_up(
        cls,
        lead: Lead,
        scheduled_at,
        follow_up_type: str = 'CALL',
        assigned_to: User = None,
        created_by: User = None,
        notes: str = ""
    ) -> LeadFollowUp:
        """
        Schedules a new follow-up for a lead.
        """
        follow_up = LeadFollowUp.objects.create(
            lead=lead,
            follow_up_type=follow_up_type,
            scheduled_at=scheduled_at,
            assigned_to=assigned_to or lead.assigned_to or created_by,
            created_by=created_by,
            notes=notes,
            status=FollowUpStatus.PENDING
        )

        cls.recalculate_next_follow_up(lead)

        LeadActivity.objects.create(
            lead=lead,
            activity_type='FOLLOW_UP_SCHEDULED',
            performed_by=created_by,
            metadata={'scheduled_at': str(scheduled_at), 'type': follow_up_type}
        )

        return follow_up

    @classmethod
    @transaction.atomic
    def complete_follow_up(cls, follow_up: LeadFollowUp, outcome: str = "", notes: str = "", completed_by: User = None) -> LeadFollowUp:
        """
        Marks a scheduled follow-up as completed.
        """
        now = timezone.now()
        follow_up.status = FollowUpStatus.COMPLETED
        follow_up.completed_at = now
        if outcome:
            follow_up.outcome = outcome
        if notes:
            follow_up.notes = notes
        follow_up.save()

        lead = follow_up.lead
        lead.last_contacted_at = now
        lead.save(update_fields=['last_contacted_at'])

        cls.recalculate_next_follow_up(lead)

        LeadActivity.objects.create(
            lead=lead,
            activity_type='FOLLOW_UP_COMPLETED',
            performed_by=completed_by,
            metadata={'outcome': outcome}
        )

        return follow_up

    @classmethod
    def recalculate_next_follow_up(cls, lead: Lead):
        earliest_pending = LeadFollowUp.objects.filter(
            lead=lead,
            status=FollowUpStatus.PENDING
        ).order_by('scheduled_at').first()

        lead.next_follow_up_at = earliest_pending.scheduled_at if earliest_pending else None
        lead.save(update_fields=['next_follow_up_at'])

class LeadStatusService:

    @classmethod
    @transaction.atomic
    def transition_status(cls, lead: Lead, new_status: str, performed_by: User = None, lost_reason: str = "") -> Lead:
        """
        Executes pipeline status transition for a Lead.
        """
        old_status = lead.status
        if old_status == new_status:
            return lead

        if new_status == LeadStatus.LOST and not lost_reason:
            raise ValidationError({"lost_reason": "A lost_reason is required when marking a Lead as LOST."})

        lead.status = new_status
        if new_status == LeadStatus.LOST:
            lead.lost_reason = lost_reason

        lead.save(update_fields=['status', 'lost_reason'])

        activity_name = 'STATUS_CHANGED'
        if old_status == LeadStatus.LOST and new_status != LeadStatus.LOST:
            activity_name = 'REOPENED'

        LeadActivity.objects.create(
            lead=lead,
            activity_type=activity_name,
            performed_by=performed_by,
            metadata={'old_status': old_status, 'new_status': new_status}
        )

        return lead

class LeadConversionService:

    @classmethod
    @transaction.atomic
    def convert_to_student(
        cls,
        lead: Lead,
        course=None,
        converted_by: User = None,
        create_enrollment: bool = True,
        enrollment_access_type: str = 'FULL'
    ) -> tuple[User, StudentProfile, object | None]:
        """
        Converts a Lead into a User and StudentProfile, optionally creating an Enrollment.
        Preserves the original Lead row for attribution analytics.
        """
        # Idempotent return if already converted
        if lead.status == LeadStatus.CONVERTED and lead.converted_user and lead.converted_student:
            return lead.converted_user, lead.converted_student, None

        # 1. Find or Create User
        user = None
        if lead.email:
            user = User.objects.filter(email__iexact=lead.email, academy=lead.academy).first()
        if not user and lead.phone:
            user = User.objects.filter(phone=lead.phone, academy=lead.academy).first()

        if not user:
            user_email = lead.email or f"lead_{lead.id.hex[:8]}@noemail.local"
            user = User.objects.create_user(
                email=user_email,
                full_name=lead.full_name,
                phone=lead.phone,
                role_code=SystemRoleCode.STUDENT,
                academy=lead.academy,
                is_email_verified=False,
                password_setup_completed=False
            )

        # 2. Find or Create StudentProfile
        student_code = f"STD-{lead.academy.id.hex[:4].upper()}-{User.objects.filter(academy=lead.academy, role_code=SystemRoleCode.STUDENT).count() + 1}"
        student_profile, _ = StudentProfile.objects.get_or_create(
            user=user,
            defaults={
                'student_code': student_code,
                'display_name': lead.full_name,
            }
        )

        # 3. Optional Course Enrollment via EnrollmentService
        enrollment = None
        if course and create_enrollment:
            if course.academy != lead.academy:
                raise ValidationError("Course does not belong to the Lead's Academy.")
            enrollment = EnrollmentService.enroll_student(
                student=user,
                course=course,
                access_type=enrollment_access_type,
                source='LEAD_CONVERSION',
                created_by=converted_by
            )

        # 4. Mark Lead as CONVERTED
        now = timezone.now()
        lead.status = LeadStatus.CONVERTED
        lead.converted_user = user
        lead.converted_student = student_profile
        lead.converted_at = now
        lead.save(update_fields=['status', 'converted_user', 'converted_student', 'converted_at'])

        LeadActivity.objects.create(
            lead=lead,
            activity_type='LEAD_CONVERTED',
            performed_by=converted_by,
            metadata={
                'converted_user_id': str(user.id),
                'converted_student_id': str(student_profile.id),
                'course_id': str(course.id) if course else None
            }
        )

        return user, student_profile, enrollment

class LeadNoteService:

    @classmethod
    @transaction.atomic
    def add_note(cls, lead: Lead, author: User, content: str, is_pinned: bool = False) -> LeadNote:
        note = LeadNote.objects.create(
            lead=lead,
            author=author,
            content=content,
            is_pinned=is_pinned
        )

        LeadActivity.objects.create(
            lead=lead,
            activity_type='NOTE_ADDED',
            performed_by=author,
            metadata={'note_id': str(note.id)}
        )

        return note
