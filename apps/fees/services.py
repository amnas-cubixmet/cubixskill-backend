import logging
import random
from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db import models, transaction
from django.utils import timezone
from enrollments.models import Enrollment, EnrollmentStatus
from fees.models import (
    CourseDefaultFeePlan,
    FeeAdjustment,
    FeeInstallment,
    FeePayment,
    FeePaymentAllocation,
    InstallmentStatus,
    StudentFeeAccount,
    StudentFeeAccountStatus,
    StudentFeePlanType,
)
from notifications.models import Notification, NotificationType
from payments.models import PaymentMethod
from rest_framework.exceptions import ValidationError
from users_roles.models import User

logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# 1. Fee Account & Course Fee Plan Service
# --------------------------------------------------------------

class FeeAccountService:

    @classmethod
    @transaction.atomic
    def save_course_default_fee_plan(
        cls,
        course,
        plan_type: str = StudentFeePlanType.ONE_TIME,
        total_fee_amount: Decimal = Decimal('0.00'),
        start_date = None,
        currency: str = 'INR',
        number_of_installments: int = 1,
        custom_installments: list = None,
        notes: str = '',
        created_by: User = None
    ) -> dict:
        """
        Configures or updates the Course-level default fee plan AND applies it
        to all currently enrolled active students.
        The course selling price (course.sale_price if set else course.price) is canonical.
        """
        if isinstance(start_date, str) and start_date.strip():
            from datetime import datetime
            try:
                start_date = datetime.strptime(start_date.strip(), '%Y-%m-%d').date()
            except Exception:
                start_date = timezone.now().date()
        else:
            start_date = start_date or timezone.now().date()

        # Canonical price determination from Course model
        course_price = course.sale_price if (course.sale_price is not None and course.sale_price > Decimal('0.00')) else course.price
        total_fee_decimal = Decimal(str(course_price)) if course_price is not None else Decimal('0.00')

        default_plan, _ = CourseDefaultFeePlan.objects.get_or_create(
            course=course,
            defaults={
                'plan_type': plan_type,
                'total_fee': total_fee_decimal,
                'currency': currency,
                'number_of_installments': number_of_installments,
                'start_date': start_date,
                'custom_installments': custom_installments or [],
                'notes': notes
            }
        )

        default_plan.plan_type = plan_type
        default_plan.total_fee = total_fee_decimal
        default_plan.currency = currency
        default_plan.number_of_installments = number_of_installments
        default_plan.start_date = start_date
        default_plan.custom_installments = custom_installments or []
        default_plan.notes = notes
        default_plan.save()

        # Apply default fee configuration to all active enrolled students
        enrollments = Enrollment.objects.filter(
            course=course,
            status=EnrollmentStatus.ACTIVE
        ).select_related('student')

        accounts_created = 0
        accounts_existing = 0

        for enr in enrollments:
            if not enr.student:
                continue

            acc_exists = StudentFeeAccount.objects.filter(course=course, student=enr.student).exists()
            if acc_exists:
                accounts_existing += 1
            else:
                accounts_created += 1

            cls.configure_student_fee_account(
                student=enr.student,
                course=course,
                plan_type=plan_type,
                total_fee_amount=total_fee_decimal,
                start_date=start_date,
                currency=currency,
                number_of_installments=number_of_installments,
                custom_installments=custom_installments,
                notes=notes,
                created_by=created_by
            )

        return {
            "course_id": str(course.id),
            "configuration_id": str(default_plan.id),
            "plan_type": default_plan.plan_type,
            "currency": default_plan.currency,
            "total_fee": float(default_plan.total_fee),
            "number_of_installments": default_plan.number_of_installments,
            "start_date": str(default_plan.start_date),
            "students_processed": enrollments.count(),
            "accounts_created": accounts_created,
            "accounts_existing": accounts_existing
        }

    @classmethod
    @transaction.atomic
    def configure_student_fee_account(
        cls,
        student: User,
        course,
        plan_type: str = StudentFeePlanType.ONE_TIME,
        total_fee_amount: Decimal = Decimal('0.00'),
        start_date = None,
        currency: str = 'INR',
        number_of_installments: int = 1,
        custom_installments: list = None,
        notes: str = '',
        created_by: User = None
    ) -> StudentFeeAccount:
        """
        Creates or updates a student's course fee account, generates installment schedule,
        preserving existing payment/waiver records.
        Canonical Course price is always used for total_fee_amount.
        """
        academy = course.academy
        if isinstance(start_date, str) and start_date.strip():
            from datetime import datetime
            try:
                start_date = datetime.strptime(start_date.strip(), '%Y-%m-%d').date()
            except Exception:
                start_date = timezone.now().date()
        else:
            start_date = start_date or timezone.now().date()

        enrollment = Enrollment.objects.filter(
            course=course,
            student=student,
            status=EnrollmentStatus.ACTIVE
        ).first()

        # Canonical price determination from Course model
        course_price = course.sale_price if (course.sale_price is not None and course.sale_price > Decimal('0.00')) else course.price
        total_fee_decimal = Decimal(str(course_price)) if course_price is not None else Decimal('0.00')

        account, created = StudentFeeAccount.objects.get_or_create(
            course=course,
            student=student,
            defaults={
                'academy': academy,
                'enrollment': enrollment,
                'plan_type': plan_type,
                'currency': currency,
                'total_fee_amount': total_fee_decimal,
                'effective_fee_amount': total_fee_decimal,
                'start_date': start_date,
                'notes': notes,
                'created_by': created_by
            }
        )

        if not created:
            account.plan_type = plan_type
            account.currency = currency
            # Preserve existing total_fee_amount snapshot unless total_fee_amount was zero
            if account.total_fee_amount == Decimal('0.00'):
                account.total_fee_amount = total_fee_decimal
            account.start_date = start_date
            account.notes = notes
            if enrollment:
                account.enrollment = enrollment
            account.save()

        # Recalculate effective fee amount accounting for existing waivers
        total_waivers = FeeAdjustment.objects.filter(
            fee_account=account,
            adjustment_type='WAIVER'
        ).aggregate(sum_w=models.Sum('amount'))['sum_w'] or Decimal('0.00')

        account.effective_fee_amount = max(Decimal('0.00'), account.total_fee_amount - total_waivers)
        account.save(update_fields=['effective_fee_amount'])

        cls._generate_installment_schedule(
            account=account,
            plan_type=plan_type,
            effective_amount=account.effective_fee_amount,
            start_date=start_date,
            number_of_installments=number_of_installments,
            custom_installments=custom_installments
        )

        cls.recalculate_account_status(account)
        return account

    @classmethod
    def _generate_installment_schedule(
        cls,
        account: StudentFeeAccount,
        plan_type: str,
        effective_amount: Decimal,
        start_date,
        number_of_installments: int = 1,
        custom_installments: list = None
    ):
        FeeInstallment.objects.filter(fee_account=account, paid_amount=Decimal('0.00')).delete()

        existing_paid = list(FeeInstallment.objects.filter(fee_account=account).order_by('sequence'))
        already_allocated_amount = sum(inst.paid_amount for inst in existing_paid)
        remaining_amount_to_schedule = max(Decimal('0.00'), effective_amount - already_allocated_amount)

        if remaining_amount_to_schedule <= Decimal('0.00') and existing_paid:
            return

        start_seq = len(existing_paid) + 1

        if plan_type == StudentFeePlanType.CUSTOM and custom_installments:
            total_custom = sum(Decimal(str(item.get('amount', 0))) for item in custom_installments)
            if abs(total_custom - effective_amount) > Decimal('0.01'):
                raise ValidationError({"custom_installments": [f"Sum of custom installments ({total_custom}) must equal total fee amount ({effective_amount})."]})

            for idx, item in enumerate(custom_installments):
                due_d = item.get('due_date')
                if isinstance(due_d, str):
                    from datetime import datetime
                    due_d = datetime.strptime(due_d, '%Y-%m-%d').date()
                amt = Decimal(str(item.get('amount', 0)))
                label = item.get('label') or f"Installment {start_seq + idx}"

                FeeInstallment.objects.create(
                    fee_account=account,
                    sequence=start_seq + idx,
                    label=label,
                    due_date=due_d,
                    amount=amt,
                    paid_amount=Decimal('0.00'),
                    status=InstallmentStatus.UPCOMING if due_d >= timezone.now().date() else InstallmentStatus.OVERDUE
                )
            return

        num_inst = max(1, number_of_installments)
        if plan_type == StudentFeePlanType.ONE_TIME:
            num_inst = 1

        base_amount = (remaining_amount_to_schedule / Decimal(str(num_inst))).quantize(Decimal('0.01'))
        remainder = remaining_amount_to_schedule - (base_amount * Decimal(str(num_inst)))

        today = timezone.now().date()

        for i in range(num_inst):
            inst_amount = base_amount + (remainder if i == num_inst - 1 else Decimal('0.00'))

            if plan_type == StudentFeePlanType.WEEKLY:
                due_d = start_date + timedelta(weeks=i)
                label = f"Week {i + 1}"
            elif plan_type == StudentFeePlanType.MONTHLY:
                due_d = start_date + relativedelta(months=i)
                label = f"Month {i + 1}"
            elif plan_type == StudentFeePlanType.QUARTERLY:
                due_d = start_date + relativedelta(months=i * 3)
                label = f"Quarter {i + 1}"
            elif plan_type == StudentFeePlanType.HALF_YEARLY:
                due_d = start_date + relativedelta(months=i * 6)
                label = f"Half-Year {i + 1}"
            elif plan_type == StudentFeePlanType.YEARLY:
                due_d = start_date + relativedelta(years=i)
                label = f"Year {i + 1}"
            else:
                due_d = start_date
                label = "Full Fee Payment"

            st = InstallmentStatus.UPCOMING
            if due_d < today:
                st = InstallmentStatus.OVERDUE

            FeeInstallment.objects.create(
                fee_account=account,
                sequence=start_seq + i,
                label=label,
                due_date=due_d,
                amount=inst_amount,
                paid_amount=Decimal('0.00'),
                status=st
            )

    @classmethod
    def recalculate_account_status(cls, account: StudentFeeAccount):
        today = timezone.now().date()
        installments = list(account.installments.all().order_by('sequence'))
        payments = FeePayment.objects.filter(fee_account=account, status='COMPLETED')
        total_paid = sum(p.amount for p in payments) or Decimal('0.00')

        if account.effective_fee_amount <= Decimal('0.00'):
            account.status = StudentFeeAccountStatus.WAIVED if account.total_fee_amount > 0 else StudentFeeAccountStatus.PAID
            account.save(update_fields=['status'])
            return

        has_overdue = False
        for inst in installments:
            remaining = inst.amount - inst.paid_amount - inst.waived_amount
            if remaining <= Decimal('0.00'):
                inst.status = InstallmentStatus.PAID
            elif inst.paid_amount > Decimal('0.00'):
                inst.status = InstallmentStatus.PARTIALLY_PAID
                if inst.due_date < today:
                    has_overdue = True
            elif inst.due_date < today:
                inst.status = InstallmentStatus.OVERDUE
                has_overdue = True
            else:
                inst.status = InstallmentStatus.UPCOMING
            inst.save(update_fields=['status', 'paid_amount'])

        outstanding = account.effective_fee_amount - total_paid

        if outstanding <= Decimal('0.00'):
            account.status = StudentFeeAccountStatus.PAID
        elif total_paid > Decimal('0.00'):
            account.status = StudentFeeAccountStatus.OVERDUE if has_overdue else StudentFeeAccountStatus.PARTIALLY_PAID
        else:
            account.status = StudentFeeAccountStatus.OVERDUE if has_overdue else StudentFeeAccountStatus.UNPAID

        account.save(update_fields=['status'])


# --------------------------------------------------------------
# 2. Fee Collection Service
# --------------------------------------------------------------

class FeeCollectionService:

    @classmethod
    @transaction.atomic
    def record_payment(
        cls,
        fee_account: StudentFeeAccount,
        amount: Decimal,
        payment_date = None,
        collection_mode: str = 'DIRECT_ACADEMY',
        payment_method: str = PaymentMethod.UPI,
        reference_number: str = '',
        gateway_order_id: str = '',
        gateway_payment_id: str = '',
        gateway_signature: str = '',
        target_installment_id: str = None,
        notes: str = '',
        recorded_by: User = None,
        send_receipt_email: bool = False
    ) -> FeePayment:
        """
        Records a fee payment atomically with select_for_update row-locking.
        Allocates to oldest unpaid installment first.
        Creates platform settlement liability ONLY if collection_mode == CUBIXSKILL_GATEWAY.
        """
        # Lock fee account row for race condition prevention
        account = StudentFeeAccount.objects.select_for_update().get(id=fee_account.id)

        payment_amount = Decimal(str(amount))
        if payment_amount <= Decimal('0.00'):
            raise ValidationError({"amount": ["Payment amount must be greater than 0."]})

        current_paid = FeePayment.objects.filter(fee_account=account, status='COMPLETED').aggregate(s=models.Sum('amount'))['s'] or Decimal('0.00')
        payable_balance = max(Decimal('0.00'), account.effective_fee_amount - current_paid)

        if payment_amount > payable_balance:
            raise ValidationError({"amount": [f"Payment amount ({payment_amount}) exceeds current remaining balance ({payable_balance})."]})

        # Idempotency check for gateway payment ID
        if gateway_payment_id:
            existing = FeePayment.objects.filter(gateway_payment_id=gateway_payment_id).first()
            if existing:
                return existing

        payment_date = payment_date or timezone.now().date()

        year_str = timezone.now().strftime('%Y')
        rnd_seq = random.randint(100000, 999999)
        receipt_number = f"RCPT-{year_str}-{rnd_seq}"
        while FeePayment.objects.filter(receipt_number=receipt_number).exists():
            rnd_seq = random.randint(100000, 999999)
            receipt_number = f"RCPT-{year_str}-{rnd_seq}"

        payment = FeePayment.objects.create(
            fee_account=account,
            student=account.student,
            course=account.course,
            receipt_number=receipt_number,
            amount=payment_amount,
            currency=account.currency,
            payment_date=payment_date,
            collection_mode=collection_mode,
            payment_method=payment_method,
            reference_number=reference_number,
            gateway_order_id=gateway_order_id,
            gateway_payment_id=gateway_payment_id,
            gateway_signature=gateway_signature,
            notes=notes,
            status='COMPLETED',
            recorded_by=recorded_by
        )

        # Allocation: oldest unpaid installment first
        unallocated = payment_amount
        installments = list(account.installments.select_for_update().order_by('sequence'))

        if target_installment_id:
            target_inst = next((i for i in installments if str(i.id) == str(target_installment_id)), None)
            if target_inst:
                due_on_target = max(Decimal('0.00'), target_inst.amount - target_inst.paid_amount - target_inst.waived_amount)
                alloc_to_target = min(unallocated, due_on_target)
                if alloc_to_target > Decimal('0.00'):
                    FeePaymentAllocation.objects.create(
                        payment=payment,
                        installment=target_inst,
                        allocated_amount=alloc_to_target
                    )
                    target_inst.paid_amount += alloc_to_target
                    target_inst.save(update_fields=['paid_amount'])
                    unallocated -= alloc_to_target

        if unallocated > Decimal('0.00'):
            for inst in installments:
                if unallocated <= Decimal('0.00'):
                    break
                due_amt = max(Decimal('0.00'), inst.amount - inst.paid_amount - inst.waived_amount)
                if due_amt <= Decimal('0.00'):
                    continue
                alloc_amt = min(unallocated, due_amt)
                FeePaymentAllocation.objects.create(
                    payment=payment,
                    installment=inst,
                    allocated_amount=alloc_amt
                )
                inst.paid_amount += alloc_amt
                inst.save(update_fields=['paid_amount'])
                unallocated -= alloc_amt

        FeeAccountService.recalculate_account_status(account)

        # Platform settlement ledger creation ONLY for CUBIXSKILL_GATEWAY
        if collection_mode == 'CUBIXSKILL_GATEWAY' and account.course.academy:
            from payments.models import AcademySettlement, SettlementStatus
            platform_fee = (payment_amount * Decimal('0.05')).quantize(Decimal('0.01'))
            gateway_fee = (payment_amount * Decimal('0.02')).quantize(Decimal('0.01'))
            net_academy = payment_amount - platform_fee - gateway_fee

            AcademySettlement.objects.create(
                academy=account.course.academy,
                period_start=timezone.now(),
                period_end=timezone.now(),
                gross_amount=payment_amount,
                gateway_fee=gateway_fee,
                platform_fee=platform_fee,
                net_amount=net_academy,
                settlement_method='UPI',
                status=SettlementStatus.PENDING
            )

        academy = account.course.academy if account.course else None
        Notification.objects.create(
            recipient=account.student,
            notification_type=NotificationType.LIVE_SESSION_CREATED,
            title="Fee Payment Received",
            message=f"Receipt {receipt_number}: Received {account.currency} {payment_amount} for {account.course.title}.",
            action_type="LINK",
            action_url=f"/courses/{account.course.id}/fees",
            source_type="FEE_PAYMENT",
            source_id=str(payment.id),
            academy=academy
        )

        return payment

    @classmethod
    @transaction.atomic
    def waive_fee(
        cls,
        fee_account: StudentFeeAccount,
        amount: Decimal,
        reason: str = '',
        authorized_by: User = None
    ) -> FeeAdjustment:
        waive_amount = Decimal(str(amount))
        if waive_amount <= Decimal('0.00'):
            raise ValidationError({"amount": ["Waiver amount must be greater than 0."]})

        adjustment = FeeAdjustment.objects.create(
            fee_account=fee_account,
            adjustment_type='WAIVER',
            amount=waive_amount,
            reason=reason,
            authorized_by=authorized_by
        )

        total_waivers = FeeAdjustment.objects.filter(
            fee_account=fee_account,
            adjustment_type='WAIVER'
        ).aggregate(sum_w=models.Sum('amount'))['sum_w'] or Decimal('0.00')

        fee_account.effective_fee_amount = max(Decimal('0.00'), fee_account.total_fee_amount - total_waivers)
        fee_account.save(update_fields=['effective_fee_amount'])

        unallocated_waiver = waive_amount
        installments = list(fee_account.installments.all().order_by('-sequence'))
        for inst in installments:
            if unallocated_waiver <= Decimal('0.00'):
                break
            remaining = max(Decimal('0.00'), inst.amount - inst.paid_amount - inst.waived_amount)
            if remaining <= Decimal('0.00'):
                continue
            apply_w = min(unallocated_waiver, remaining)
            inst.waived_amount += apply_w
            inst.save(update_fields=['waived_amount'])
            unallocated_waiver -= apply_w

        FeeAccountService.recalculate_account_status(fee_account)
        return adjustment


# --------------------------------------------------------------
# 3. Fee Reminder Service
# --------------------------------------------------------------

class FeeReminderService:

    @classmethod
    def send_fee_reminder(
        cls,
        fee_account: StudentFeeAccount,
        send_email: bool = False,
        reminder_type: str = 'DUE'
    ) -> bool:
        student = fee_account.student
        course = fee_account.course
        academy = course.academy if course else None

        payments = FeePayment.objects.filter(fee_account=fee_account, status='COMPLETED')
        total_paid = sum(p.amount for p in payments) or Decimal('0.00')
        balance = max(Decimal('0.00'), fee_account.effective_fee_amount - total_paid)

        next_inst = fee_account.installments.filter(
            status__in=[InstallmentStatus.UPCOMING, InstallmentStatus.DUE, InstallmentStatus.OVERDUE]
        ).order_by('due_date').first()

        due_date_str = str(next_inst.due_date) if next_inst else "Immediate"
        amount_due_str = f"{fee_account.currency} {next_inst.amount - next_inst.paid_amount}" if next_inst else f"{fee_account.currency} {balance}"

        title = "Fee Payment Reminder" if reminder_type == 'DUE' else "Fee Payment Overdue"
        msg = f"Reminder: {amount_due_str} for '{course.title}' is due on {due_date_str}. Total outstanding balance: {fee_account.currency} {balance}."

        Notification.objects.create(
            recipient=student,
            notification_type=NotificationType.LIVE_SESSION_STARTING_SOON,
            title=title,
            message=msg,
            action_type="LINK",
            action_url=f"/courses/{course.id}/fees",
            source_type="FEE_REMINDER",
            source_id=str(fee_account.id),
            academy=academy
        )

        if send_email and student.email:
            try:
                from emails.outbox_service import EmailJobService
                context = {
                    "student_name": student.full_name or student.email.split('@')[0],
                    "academy_name": academy.name if academy else "CubixSkill Academy",
                    "course_title": course.title,
                    "amount_due": amount_due_str,
                    "due_date": due_date_str,
                    "outstanding_balance": f"{fee_account.currency} {balance}",
                }
                EmailJobService.create_transactional_job(
                    recipient_email=student.email,
                    subject=f"{title}: {course.title}",
                    template_name="fee_reminder",
                    context=context,
                    academy_uuid=academy.id if academy else None,
                    recipient_user_uuid=student.user.id if hasattr(student, 'user') and student.user else None,
                    recipient_name=student.full_name or student.email.split('@')[0]
                )
            except Exception as exc:
                logger.error(f"Failed to queue fee reminder email for student {student.id}: {exc}")

        return True
