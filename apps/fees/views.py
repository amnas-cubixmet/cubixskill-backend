from decimal import Decimal
from django.utils import timezone
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from core.permissions import CanAccessAcademyPermission
from core.utils import api_response
from courses.models import Course
from users_roles.models import User
from enrollments.models import Enrollment, EnrollmentStatus
from fees.models import (
    StudentFeeAccount,
    FeeInstallment,
    FeePayment,
    FeeAdjustment,
    StudentFeeAccountStatus,
    InstallmentStatus,
    StudentFeePlanType,
)
from fees.services import (
    FeeAccountService,
    FeeCollectionService,
    FeeReminderService,
)
from fees.selectors import FeeCollectionAnalyticsSelector
from payments.models import PaymentMethod

# --------------------------------------------------------------
# 1. Course Fee Collection Summary API
# --------------------------------------------------------------

class CourseFeeSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return api_response(message="Course not found.", status_code=status.HTTP_404_NOT_FOUND)

        summary = FeeCollectionAnalyticsSelector.get_course_fee_summary(course)
        return api_response(data=summary, message="Course fee summary fetched successfully.")


# --------------------------------------------------------------
# 1B. Course Default Fee Configuration API
# --------------------------------------------------------------

class CourseDefaultFeePlanView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return api_response(message="Course not found.", status_code=status.HTTP_404_NOT_FOUND)

        from fees.models import CourseDefaultFeePlan
        plan = CourseDefaultFeePlan.objects.filter(course=course).first()
        if not plan:
            return api_response(
                data={"is_configured": False, "course_id": str(course.id)},
                message="Course default fee plan is not configured."
            )

        return api_response(
            data={
                "is_configured": True,
                "configuration_id": str(plan.id),
                "course_id": str(course.id),
                "plan_type": plan.plan_type,
                "total_fee": float(plan.total_fee),
                "currency": plan.currency,
                "number_of_installments": plan.number_of_installments,
                "start_date": str(plan.start_date),
                "custom_installments": plan.custom_installments,
                "notes": plan.notes
            },
            message="Course fee configuration loaded successfully."
        )

    def post(self, request, course_id=None):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return api_response(message="Course not found.", status_code=status.HTTP_404_NOT_FOUND)

        plan_type = request.data.get('plan_type', StudentFeePlanType.ONE_TIME)
        total_fee = request.data.get('total_fee_amount', 0)
        start_date = request.data.get('start_date')
        currency = request.data.get('currency', 'INR')
        number_of_installments = request.data.get('number_of_installments', 1)
        custom_installments = request.data.get('custom_installments')
        notes = request.data.get('notes', '')

        result = FeeAccountService.save_course_default_fee_plan(
            course=course,
            plan_type=plan_type,
            total_fee_amount=total_fee,
            start_date=start_date,
            currency=currency,
            number_of_installments=number_of_installments,
            custom_installments=custom_installments,
            notes=notes,
            created_by=request.user
        )

        return api_response(
            data=result,
            message=f"Course fee plan configured and applied to {result['students_processed']} students successfully.",
            status_code=status.HTTP_200_OK
        )


# --------------------------------------------------------------
# 2. Student Fee Account List & Create API
# --------------------------------------------------------------

class StudentFeeAccountListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return api_response(message="Course not found.", status_code=status.HTTP_404_NOT_FOUND)

        search = (request.query_params.get('search') or '').strip().lower()
        status_filter = (request.query_params.get('status') or '').strip()
        if status_filter.lower() == 'all':
            status_filter = ''

        today = timezone.now().date()

        enrollments = Enrollment.objects.filter(
            course=course,
            status=EnrollmentStatus.ACTIVE
        ).select_related('student', 'student__student_profile')

        accounts_by_user = {
            acc.student_id: acc
            for acc in StudentFeeAccount.objects.filter(course=course).prefetch_related('installments', 'payments')
        }

        records = []

        for enr in enrollments:
            student = enr.student
            if not student:
                continue

            full_name = student.full_name or student.email.split('@')[0]
            email = student.email
            phone = getattr(student, 'phone_number', '') or ''
            student_code = getattr(getattr(student, 'student_profile', None), 'student_code', f"STU-{student.id.hex[:6].upper()}")
            avatar_url = getattr(getattr(student, 'student_profile', None), 'profile_picture_url', '') or 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100'

            if search:
                if not (search in full_name.lower() or search in email.lower() or search in student_code.lower() or search in phone.lower()):
                    continue

            acc = accounts_by_user.get(student.id)

            if acc:
                fee_account_id = str(acc.id)
                plan_type = acc.plan_type
                total_fee = float(acc.total_fee_amount)
                effective_fee = float(acc.effective_fee_amount)
                payments = [p for p in acc.payments.all() if p.status == 'COMPLETED']
                total_paid = float(sum(p.amount for p in payments)) if payments else 0.0
                balance = max(0.0, effective_fee - total_paid)

                upcoming_insts = [i for i in acc.installments.all() if i.status in [InstallmentStatus.UPCOMING, InstallmentStatus.DUE, InstallmentStatus.OVERDUE, InstallmentStatus.PARTIAL]]
                upcoming_insts.sort(key=lambda i: i.due_date)
                next_due_date = str(upcoming_insts[0].due_date) if upcoming_insts else None

                overdue_insts = [i for i in acc.installments.all() if i.status == InstallmentStatus.OVERDUE or (i.due_date < today and float(i.amount - i.paid_amount - i.waived_amount) > 0)]
                overdue_amount = float(sum(max(Decimal('0.00'), i.amount - i.paid_amount - i.waived_amount) for i in overdue_insts)) if overdue_insts else 0.0

                fee_status = acc.status
            else:
                fee_account_id = None
                plan_type = "NONE"
                total_fee = 0.0
                effective_fee = 0.0
                total_paid = 0.0
                balance = 0.0
                next_due_date = None
                overdue_amount = 0.0
                fee_status = StudentFeeAccountStatus.NOT_CONFIGURED

            if status_filter and fee_status.lower() != status_filter.lower():
                continue

            records.append({
                "student_id": str(student.id),
                "student_code": student_code,
                "student_name": full_name,
                "student_email": email,
                "student_phone": phone,
                "avatar_url": avatar_url,
                "fee_account_id": fee_account_id,
                "plan_type": plan_type,
                "total_fee": total_fee,
                "effective_fee": effective_fee,
                "paid_amount": total_paid,
                "balance": balance,
                "next_due_date": next_due_date,
                "overdue_amount": overdue_amount,
                "status": fee_status,
                "currency": acc.currency if acc else "INR"
            })

        return api_response(data=records, message="Student fee records fetched successfully.")

    def post(self, request, course_id=None):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return api_response(message="Course not found.", status_code=status.HTTP_404_NOT_FOUND)

        student_id = request.data.get('student_id')
        if not student_id:
            raise ValidationError({"student_id": ["Student ID is required."]})

        try:
            student = User.objects.get(id=student_id)
        except User.DoesNotExist:
            raise ValidationError({"student_id": ["Student user not found."]})

        plan_type = request.data.get('plan_type', StudentFeePlanType.ONE_TIME)
        total_fee = request.data.get('total_fee_amount', 0)
        start_date = request.data.get('start_date')
        currency = request.data.get('currency', 'INR')
        number_of_installments = request.data.get('number_of_installments', 1)
        custom_installments = request.data.get('custom_installments')
        notes = request.data.get('notes', '')

        account = FeeAccountService.configure_student_fee_account(
            student=student,
            course=course,
            plan_type=plan_type,
            total_fee_amount=total_fee,
            start_date=start_date,
            currency=currency,
            number_of_installments=number_of_installments,
            custom_installments=custom_installments,
            notes=notes,
            created_by=request.user
        )

        return api_response(
            data={"fee_account_id": str(account.id), "status": account.status},
            message="Student fee account configured successfully.",
            status_code=status.HTTP_201_CREATED
        )


# --------------------------------------------------------------
# 3. Student Fee Detail Drawer API
# --------------------------------------------------------------

class StudentFeeAccountDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None, account_id=None):
        try:
            account = StudentFeeAccount.objects.select_related('student', 'student__student_profile', 'course').prefetch_related(
                'installments', 'payments', 'adjustments'
            ).get(id=account_id, course_id=course_id)
        except StudentFeeAccount.DoesNotExist:
            return api_response(message="Student fee account not found.", status_code=status.HTTP_404_NOT_FOUND)

        installments_data = [
            {
                "id": str(inst.id),
                "sequence": inst.sequence,
                "label": inst.label,
                "due_date": str(inst.due_date),
                "amount": float(inst.amount),
                "paid_amount": float(inst.paid_amount),
                "waived_amount": float(inst.waived_amount),
                "remaining_amount": float(max(Decimal('0.00'), inst.amount - inst.paid_amount - inst.waived_amount)),
                "status": inst.status
            }
            for inst in account.installments.all()
        ]

        payments_data = [
            {
                "id": str(p.id),
                "receipt_number": p.receipt_number,
                "amount": float(p.amount),
                "currency": p.currency,
                "payment_date": str(p.payment_date),
                "payment_method": p.payment_method,
                "reference_number": p.reference_number,
                "notes": p.notes,
                "recorded_by": p.recorded_by.full_name if p.recorded_by else "Admin"
            }
            for p in account.payments.filter(status='COMPLETED')
        ]

        adjustments_data = [
            {
                "id": str(adj.id),
                "adjustment_type": adj.adjustment_type,
                "amount": float(adj.amount),
                "reason": adj.reason,
                "authorized_by": adj.authorized_by.full_name if adj.authorized_by else "Admin",
                "created_at": str(adj.created_at)
            }
            for adj in account.adjustments.all()
        ]

        total_paid = float(sum(p.amount for p in account.payments.filter(status='COMPLETED')))
        balance = float(max(Decimal('0.00'), account.effective_fee_amount - Decimal(str(total_paid))))

        detail_data = {
            "fee_account_id": str(account.id),
            "student_id": str(account.student.id),
            "student_name": account.student.full_name or account.student.email.split('@')[0],
            "student_email": account.student.email,
            "student_code": getattr(getattr(account.student, 'student_profile', None), 'student_code', f"STU-{account.student.id.hex[:6].upper()}"),
            "course_id": str(account.course.id),
            "course_title": account.course.title,
            "plan_type": account.plan_type,
            "currency": account.currency,
            "total_fee_amount": float(account.total_fee_amount),
            "effective_fee_amount": float(account.effective_fee_amount),
            "total_paid": total_paid,
            "balance": balance,
            "status": account.status,
            "installments": installments_data,
            "payments": payments_data,
            "adjustments": adjustments_data
        }

        return api_response(data=detail_data, message="Student fee account detail loaded successfully.")


# --------------------------------------------------------------
# 4. Collect Payment API
# --------------------------------------------------------------

class CollectFeePaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def post(self, request, course_id=None, account_id=None):
        try:
            account = StudentFeeAccount.objects.get(id=account_id, course_id=course_id)
        except StudentFeeAccount.DoesNotExist:
            return api_response(message="Fee account not found.", status_code=status.HTTP_404_NOT_FOUND)

        amount = request.data.get('amount')
        if not amount:
            raise ValidationError({"amount": ["Payment amount is required."]})

        payment_date = request.data.get('payment_date')
        payment_method = request.data.get('payment_method', PaymentMethod.UPI)
        reference_number = request.data.get('reference_number', '')
        target_installment_id = request.data.get('target_installment_id')
        notes = request.data.get('notes', '')
        send_receipt_email = request.data.get('send_receipt_email', False)

        payment = FeeCollectionService.record_payment(
            fee_account=account,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            reference_number=reference_number,
            target_installment_id=target_installment_id,
            notes=notes,
            recorded_by=request.user,
            send_receipt_email=send_receipt_email
        )

        return api_response(
            data={
                "payment_id": str(payment.id),
                "receipt_number": payment.receipt_number,
                "amount": float(payment.amount),
                "status": payment.fee_account.status
            },
            message=f"Payment recorded successfully. Receipt {payment.receipt_number} generated.",
            status_code=status.HTTP_201_CREATED
        )


# --------------------------------------------------------------
# 5. Waive Fee API
# --------------------------------------------------------------

class WaiveFeeView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def post(self, request, course_id=None, account_id=None):
        try:
            account = StudentFeeAccount.objects.get(id=account_id, course_id=course_id)
        except StudentFeeAccount.DoesNotExist:
            return api_response(message="Fee account not found.", status_code=status.HTTP_404_NOT_FOUND)

        amount = request.data.get('amount')
        reason = request.data.get('reason', '')
        if not amount:
            raise ValidationError({"amount": ["Waiver amount is required."]})

        adjustment = FeeCollectionService.waive_fee(
            fee_account=account,
            amount=amount,
            reason=reason,
            authorized_by=request.user
        )

        return api_response(
            data={"adjustment_id": str(adjustment.id), "amount": float(adjustment.amount), "new_effective_fee": float(account.effective_fee_amount)},
            message="Fee waiver applied successfully."
        )


# --------------------------------------------------------------
# 6. Send Fee Reminder API
# --------------------------------------------------------------

class SendFeeReminderView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def post(self, request, course_id=None, account_id=None):
        try:
            account = StudentFeeAccount.objects.get(id=account_id, course_id=course_id)
        except StudentFeeAccount.DoesNotExist:
            return api_response(message="Fee account not found.", status_code=status.HTTP_404_NOT_FOUND)

        send_email = request.data.get('send_email', False)
        reminder_type = request.data.get('reminder_type', 'DUE')

        FeeReminderService.send_fee_reminder(
            fee_account=account,
            send_email=send_email,
            reminder_type=reminder_type
        )

        return api_response(message="Fee payment reminder dispatched successfully.")


# --------------------------------------------------------------
# 7. Course Fee Payments Ledger API
# --------------------------------------------------------------

class CourseFeePaymentsLedgerView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get(self, request, course_id=None):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return api_response(message="Course not found.", status_code=status.HTTP_404_NOT_FOUND)

        payments = FeePayment.objects.filter(course=course, status='COMPLETED').select_related(
            'student', 'student__student_profile', 'recorded_by'
        ).order_by('-payment_date', '-created_at')

        records = [
            {
                "id": str(p.id),
                "receipt_number": p.receipt_number,
                "student_id": str(p.student.id),
                "student_name": p.student.full_name or p.student.email.split('@')[0],
                "student_email": p.student.email,
                "student_code": getattr(getattr(p.student, 'student_profile', None), 'student_code', f"STU-{p.student.id.hex[:6].upper()}"),
                "amount": float(p.amount),
                "currency": p.currency,
                "payment_date": str(p.payment_date),
                "payment_method": p.payment_method,
                "reference_number": p.reference_number,
                "notes": p.notes,
                "recorded_by": p.recorded_by.full_name if p.recorded_by else "Admin"
            }
            for p in payments
        ]

        return api_response(data=records, message="Course payment ledger fetched successfully.")
