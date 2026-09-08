from django.db.models import QuerySet
from payments.models import PaymentContext, PaymentOrder

# --------------------------------------------------------------
# Payment Selectors
# Read-only optimized queries for payment and reconciliation workflows.
# Tenant isolation enforced by filtering by authenticated Academy context.
# --------------------------------------------------------------

class PaymentSelector:

    @classmethod
    def get_student_payment_history(cls, student) -> QuerySet[PaymentOrder]:
        """
        Returns student's course purchase payment orders.
        """
        return PaymentOrder.objects.filter(
            payer=student,
            payment_context=PaymentContext.COURSE_PURCHASE
        ).select_related('course', 'academy', 'coupon', 'invoice').prefetch_related('transactions', 'refunds').order_by('-created_at')

    @classmethod
    def get_academy_payment_history(cls, academy) -> QuerySet[PaymentOrder]:
        """
        Returns Academy payment orders for course checkouts and platform purchases.
        """
        return PaymentOrder.objects.filter(
            academy=academy
        ).select_related('course', 'payer', 'coupon', 'invoice').prefetch_related('transactions', 'refunds').order_by('-created_at')

    @classmethod
    def get_admin_payment_history(cls, status: str = None, payment_context: str = None) -> QuerySet[PaymentOrder]:
        """
        Returns platform-wide payment orders for Super Admin visibility.
        """
        queryset = PaymentOrder.objects.select_related(
            'academy', 'payer', 'course', 'plan', 'coupon', 'invoice'
        ).prefetch_related('transactions', 'refunds')

        if status:
            queryset = queryset.filter(status=status)
        if payment_context:
            queryset = queryset.filter(payment_context=payment_context)

        return queryset.order_by('-created_at')
