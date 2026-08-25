from django.urls import path
from fees.views import (
    CourseFeeSummaryView,
    CourseDefaultFeePlanView,
    StudentFeeAccountListCreateView,
    StudentFeeAccountDetailView,
    CollectFeePaymentView,
    WaiveFeeView,
    SendFeeReminderView,
    CourseFeePaymentsLedgerView,
    GlobalFeeSummaryView,
    GlobalStudentFeeAccountListView,
)

# --------------------------------------------------------------
# Fees App URL Router Configuration
# Centralized REST endpoints for student fee accounts, installment schedules,
# payments collection, waivers, and fee ledgers.
# --------------------------------------------------------------

urlpatterns = [
    # Global Academy endpoints
    path('summary/', GlobalFeeSummaryView.as_view(), name='global-fee-summary'),
    path('accounts/', GlobalStudentFeeAccountListView.as_view(), name='global-fee-accounts'),

    # Course-level endpoints
    path('courses/<uuid:course_id>/summary/', CourseFeeSummaryView.as_view(), name='fee-summary'),
    path('courses/<uuid:course_id>/fee-summary/', CourseFeeSummaryView.as_view(), name='fee-summary-legacy'),
    path('courses/<uuid:course_id>/configuration/', CourseDefaultFeePlanView.as_view(), name='course-fee-configuration'),
    path('courses/<uuid:course_id>/fee-configuration/', CourseDefaultFeePlanView.as_view(), name='course-fee-configuration-legacy'),
    path('courses/<uuid:course_id>/accounts/', StudentFeeAccountListCreateView.as_view(), name='fee-accounts'),
    path('courses/<uuid:course_id>/fee-accounts/', StudentFeeAccountListCreateView.as_view(), name='fee-accounts-legacy'),
    path('courses/<uuid:course_id>/payments/', CourseFeePaymentsLedgerView.as_view(), name='fee-payments-ledger'),
    path('courses/<uuid:course_id>/fee-payments/', CourseFeePaymentsLedgerView.as_view(), name='fee-payments-ledger-legacy'),

    # Account-level endpoints
    path('courses/<uuid:course_id>/accounts/<uuid:account_id>/', StudentFeeAccountDetailView.as_view(), name='fee-account-detail'),
    path('courses/<uuid:course_id>/fee-accounts/<uuid:account_id>/', StudentFeeAccountDetailView.as_view(), name='fee-account-detail-legacy'),
    path('courses/<uuid:course_id>/accounts/<uuid:account_id>/payments/', CollectFeePaymentView.as_view(), name='collect-fee-payment'),
    path('courses/<uuid:course_id>/fee-accounts/<uuid:account_id>/payments/', CollectFeePaymentView.as_view(), name='collect-fee-payment-legacy'),
    path('courses/<uuid:course_id>/accounts/<uuid:account_id>/waive/', WaiveFeeView.as_view(), name='waive-fee'),
    path('courses/<uuid:course_id>/fee-accounts/<uuid:account_id>/waive/', WaiveFeeView.as_view(), name='waive-fee-legacy'),
    path('courses/<uuid:course_id>/accounts/<uuid:account_id>/reminder/', SendFeeReminderView.as_view(), name='send-fee-reminder'),
    path('courses/<uuid:course_id>/fee-accounts/<uuid:account_id>/reminder/', SendFeeReminderView.as_view(), name='send-fee-reminder-legacy'),
]
