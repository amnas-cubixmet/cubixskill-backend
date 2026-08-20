from decimal import Decimal
from django.db.models import Count, Sum, Avg, Q, F
from django.utils import timezone

from academy.models import Academy
from students.models import StudentProfile, StudentStatus
from courses.models import Course, CourseStatus
from enrollments.models import Enrollment, EnrollmentStatus
from learning_progress.models import CourseProgress, ProgressStatus
from live_classes.models import LiveSession, LiveStatus, LiveSessionAttendance

from leads.models import Lead, LeadStatus
from payments.models import PaymentOrder, OrderStatus, PaymentRefund, PaymentContext
from credits.models import CreditAccount, CreditLedgerEntry, LedgerEntryType
from storage.models import MediaFile
from certificates.models import Certificate

# --------------------------------------------------------------
# Analytics Selectors
# High-performance, read-only aggregation layer over domain models.
# Current analytics may use live database queries for real-time overview.
# Analytics aggregates domain data but is not the source of truth;
# Payment, Progress, Leads, and Credits domains remain authoritative for their own data.
# Academy analytics must enforce tenant isolation.
# Platform reports may use academy = null where supported.
# Storage history must use immutable usage snapshots, not current files only.
# --------------------------------------------------------------


class AnalyticsSelector:

    @classmethod
    def get_academy_dashboard(cls, academy: Academy, date_from=None, date_to=None) -> dict:
        """
        Calculates comprehensive summary metrics for an Academy's dashboard.
        """
        now = timezone.now()

        # 1. Students
        student_qs = StudentProfile.objects.filter(user__academy=academy)
        total_students = student_qs.count()
        active_students = student_qs.filter(status=StudentStatus.ACTIVE).count()

        # 2. Courses
        course_qs = Course.objects.filter(academy=academy)
        total_courses = course_qs.count()
        published_courses = course_qs.filter(status=CourseStatus.PUBLISHED, is_active=True).count()

        # 3. Enrollments & Progress
        enrollment_qs = Enrollment.objects.filter(student__academy=academy)
        active_enrollments = enrollment_qs.filter(status=EnrollmentStatus.ACTIVE).count()
        course_completions = CourseProgress.objects.filter(student__academy=academy, status=ProgressStatus.COMPLETED).count()


        # 4. Revenue (Grouped by Currency to prevent illegal sum across currencies)
        revenue_qs = PaymentOrder.objects.filter(
            academy=academy,
            payment_context=PaymentContext.COURSE_PURCHASE,
            status=OrderStatus.COMPLETED
        )
        if date_from:
            revenue_qs = revenue_qs.filter(completed_at__gte=date_from)
        if date_to:
            revenue_qs = revenue_qs.filter(completed_at__lte=date_to)

        revenue_by_currency = {}
        for row in revenue_qs.values('currency').annotate(total=Sum('final_amount')):
            val = (row['total'] or Decimal('0.00'))
            if isinstance(val, (int, float, str)):
                val = Decimal(str(val))
            revenue_by_currency[row['currency']] = str(val.quantize(Decimal('0.01')))


        # 5. Leads
        lead_qs = Lead.objects.filter(academy=academy)
        total_leads = lead_qs.count()
        new_leads = lead_qs.filter(status=LeadStatus.NEW).count()
        converted_leads = lead_qs.filter(status=LeadStatus.CONVERTED).count()
        conversion_rate = f"{(converted_leads / total_leads * 100):.2f}%" if total_leads > 0 else "0.00%"

        # 6. Live Classes
        live_qs = LiveSession.objects.filter(course__academy=academy)
        upcoming_live_sessions = live_qs.filter(scheduled_start__gte=now, status__in=[LiveStatus.SCHEDULED, LiveStatus.LIVE]).count()

        # 7. Storage & Credits
        academy_id = academy.id if academy else None
        storage_bytes = (
            MediaFile.objects.filter(academy_uuid=academy_id, status='ACTIVE').aggregate(total=Sum('size_bytes'))['total'] or 0
        ) if academy_id else 0
        storage_gb = f"{(storage_bytes / (1024 ** 3)):.2f} GB"


        credit_account = CreditAccount.objects.filter(academy=academy).first() if academy else None
        credit_balance = str(credit_account.balance) if credit_account else "0.000000"

        # 8. Certificates
        certificates_issued = Certificate.objects.filter(student__academy=academy, status='ISSUED').count() if academy else 0


        return {
            'total_students': total_students,
            'active_students': active_students,
            'total_courses': total_courses,
            'published_courses': published_courses,
            'active_enrollments': active_enrollments,
            'course_completions': course_completions,
            'revenue_by_currency': revenue_by_currency,
            'total_leads': total_leads,
            'new_leads': new_leads,
            'converted_leads': converted_leads,
            'lead_conversion_rate': conversion_rate,
            'upcoming_live_sessions': upcoming_live_sessions,
            'storage_gb': storage_gb,
            'credit_balance': credit_balance,
            'certificates_issued': certificates_issued,
        }

    @classmethod
    def get_platform_dashboard(cls, date_from=None, date_to=None) -> dict:
        """
        Calculates platform-wide summary analytics for Super Admin.
        """
        total_academies = Academy.objects.count()
        active_academies = Academy.objects.filter(is_active=True).count()
        total_students = StudentProfile.objects.count()
        total_courses = Course.objects.count()

        platform_revenue_qs = PaymentOrder.objects.filter(status=OrderStatus.COMPLETED)
        if date_from:
            platform_revenue_qs = platform_revenue_qs.filter(completed_at__gte=date_from)
        if date_to:
            platform_revenue_qs = platform_revenue_qs.filter(completed_at__lte=date_to)

        revenue_by_currency = {}
        for row in platform_revenue_qs.values('currency').annotate(total=Sum('final_amount')):
            val = (row['total'] or Decimal('0.00'))
            if isinstance(val, (int, float, str)):
                val = Decimal(str(val))
            revenue_by_currency[row['currency']] = str(val.quantize(Decimal('0.01')))


        total_storage_bytes = MediaFile.objects.filter(status='ACTIVE').aggregate(total=Sum('size_bytes'))['total'] or 0

        return {
            'total_academies': total_academies,
            'active_academies': active_academies,
            'total_students': total_students,
            'total_courses': total_courses,
            'platform_revenue_by_currency': revenue_by_currency,
            'total_storage_gb': f"{(total_storage_bytes / (1024 ** 3)):.2f} GB",
        }

    @classmethod
    def get_course_analytics(cls, academy: Academy, course_id: str = None) -> list[dict]:
        """
        Calculates per-course metrics (enrollments, active students, completion rate, avg progress, revenue).
        """
        course_qs = Course.objects.filter(academy=academy)
        if course_id:
            course_qs = course_qs.filter(id=course_id)

        results = []
        for course in course_qs:
            total_enrollments = Enrollment.objects.filter(course=course).count()
            active_students = Enrollment.objects.filter(course=course, status=EnrollmentStatus.ACTIVE).count()

            progress_qs = CourseProgress.objects.filter(course=course)
            completed_count = progress_qs.filter(status=ProgressStatus.COMPLETED).count()
            avg_progress = progress_qs.aggregate(avg=Avg('progress_percent'))['avg'] or 0.0

            completion_rate = f"{(completed_count / total_enrollments * 100):.2f}%" if total_enrollments > 0 else "0.00%"

            revenue_row = PaymentOrder.objects.filter(
                course=course,
                status=OrderStatus.COMPLETED
            ).aggregate(total=Sum('final_amount'))['total'] or Decimal('0.00')

            results.append({
                'course_id': str(course.id),
                'course_title': course.title,
                'total_enrollments': total_enrollments,
                'active_students': active_students,
                'completed_students': completed_count,
                'completion_rate': completion_rate,
                'average_progress_percent': f"{avg_progress:.2f}%",
                'revenue': str(revenue_row.quantize(Decimal('0.01'))),
            })

        return results

    @classmethod
    def get_revenue_analytics(cls, academy: Academy) -> dict:
        """
        Calculates gross revenue, net revenue, and refunds grouped by currency for an Academy.
        """
        completed_orders = PaymentOrder.objects.filter(
            academy=academy,
            payment_context=PaymentContext.COURSE_PURCHASE,
            status__in=[OrderStatus.COMPLETED, OrderStatus.PARTIALLY_REFUNDED, OrderStatus.REFUNDED]
        )

        currencies = completed_orders.values_list('currency', flat=True).distinct()
        revenue_metrics = {}

        for curr in currencies:
            gross = (completed_orders.filter(currency=curr).aggregate(total=Sum('final_amount'))['total'] or Decimal('0.00')).quantize(Decimal('0.01'))

            refunds = (PaymentRefund.objects.filter(
                order__academy=academy,
                order__currency=curr,
                status='SUCCESS'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')).quantize(Decimal('0.01'))

            net = (gross - refunds).quantize(Decimal('0.01'))

            revenue_metrics[curr] = {
                'gross_revenue': str(gross),
                'total_refunds': str(refunds),
                'net_revenue': str(net),
            }

        return revenue_metrics

    @classmethod
    def get_lead_analytics(cls, academy: Academy) -> dict:
        """
        Calculates lead conversion rates, pipeline status breakdown, and lead source metrics.
        """
        lead_qs = Lead.objects.filter(academy=academy)
        total_leads = lead_qs.count()

        status_counts = {}
        for row in lead_qs.values('status').annotate(count=Count('id')):
            status_counts[row['status']] = row['count']

        source_counts = {}
        for row in lead_qs.values('source').annotate(count=Count('id')):
            source_counts[row['source']] = row['count']

        converted = status_counts.get(LeadStatus.CONVERTED, 0)
        conversion_rate = f"{(converted / total_leads * 100):.2f}%" if total_leads > 0 else "0.00%"

        return {
            'total_leads': total_leads,
            'conversion_rate': conversion_rate,
            'status_breakdown': status_counts,
            'source_breakdown': source_counts,
        }

    @classmethod
    def get_live_class_analytics(cls, academy: Academy) -> dict:
        """
        Calculates live session attendance rates and completed session metrics.
        """
        live_qs = LiveSession.objects.filter(course__academy=academy)
        total_sessions = live_qs.count()
        completed_sessions = live_qs.filter(status=LiveStatus.ENDED).count()

        attendance_qs = LiveSessionAttendance.objects.filter(live_session__course__academy=academy)
        total_attendances = attendance_qs.count()
        avg_attendance_minutes = attendance_qs.aggregate(avg=Avg('attendance_duration_minutes'))['avg'] or 0.0

        return {
            'total_sessions': total_sessions,
            'completed_sessions': completed_sessions,
            'total_attendance_records': total_attendances,
            'average_attendance_minutes': f"{avg_attendance_minutes:.1f}",
        }

