from django.urls import path
try:
    from . import views
except (ImportError, ValueError):
    from control_panel import views

app_name = 'control_panel'

urlpatterns = [
    # Auth & Root Dashboard
    path('', views.dashboard_view, name='dashboard'),
    path('login/', views.control_login_view, name='login'),
    path('logout/', views.control_logout_view, name='logout'),

    # Platform Entities
    path('academies/', views.academies_list_view, name='academies_list'),
    path('academies/create/', views.academy_create_view, name='academy_create'),
    path('academies/<uuid:pk>/', views.academy_detail_view, name='academy_detail'),
    path('academies/<uuid:pk>/edit/', views.academy_edit_view, name='academy_edit'),
    path('academies/<uuid:pk>/delete/', views.academy_delete_view, name='academy_delete'),
    path('academies/<uuid:pk>/action/', views.academy_action_view, name='academy_action'),
    path('academies/<uuid:pk>/courses/json/', views.academy_courses_json_view, name='academy_courses_json'),

    path('users/', views.users_list_view, name='users_list'),
    path('users/create/', views.user_create_view, name='user_create'),
    path('users/<uuid:pk>/', views.user_detail_view, name='user_detail'),
    path('users/<uuid:pk>/edit/', views.user_edit_view, name='user_edit'),
    path('users/<uuid:pk>/delete/', views.user_delete_view, name='user_delete'),
    path('users/<uuid:pk>/enable/', views.user_enable_view, name='user_enable'),
    path('users/<uuid:pk>/disable/', views.user_disable_view, name='user_disable'),

    path('students/', views.students_list_view, name='students_list'),
    path('students/create/', views.student_create_view, name='student_create'),
    path('students/<uuid:pk>/', views.student_detail_view, name='student_detail'),
    path('students/<uuid:pk>/edit/', views.student_edit_view, name='student_edit'),
    path('students/<uuid:pk>/delete/', views.student_delete_view, name='student_delete'),
    path('students/<uuid:pk>/enable/', views.student_enable_view, name='student_enable'),
    path('students/<uuid:pk>/disable/', views.student_disable_view, name='student_disable'),

    path('courses/', views.courses_list_view, name='courses_list'),
    path('courses/create/', views.course_create_view, name='course_create'),
    path('courses/<uuid:pk>/', views.course_detail_view, name='course_detail'),
    path('courses/<uuid:pk>/edit/', views.course_edit_view, name='course_edit'),
    path('courses/<uuid:pk>/delete/', views.course_delete_view, name='course_delete'),
    path('courses/<uuid:pk>/enable/', views.course_enable_view, name='course_enable'),
    path('courses/<uuid:pk>/disable/', views.course_disable_view, name='course_disable'),

    # Monetization & Pricing
    path('pricing/', views.pricing_rules_list_view, name='pricing_rules_list'),
    path('pricing/create/', views.pricing_rule_create_view, name='pricing_rule_create'),
    path('pricing/<uuid:pk>/', views.pricing_rule_detail_view, name='pricing_rule_detail'),
    path('pricing/<uuid:pk>/edit/', views.pricing_rule_edit_view, name='pricing_rule_edit'),
    path('pricing/<uuid:pk>/delete/', views.pricing_rule_delete_view, name='pricing_rule_delete'),
    path('pricing/<uuid:pk>/enable/', views.pricing_rule_enable_view, name='pricing_rule_enable'),
    path('pricing/<uuid:pk>/disable/', views.pricing_rule_disable_view, name='pricing_rule_disable'),

    path('credits/purchase-rates/', views.credit_rates_list_view, name='credit_rates'),
    path('credits/purchase-rates/create/', views.credit_rate_create_view, name='credit_rate_create'),
    path('credits/purchase-rates/<uuid:pk>/', views.credit_rate_detail_view, name='credit_rate_detail'),
    path('credits/purchase-rates/<uuid:pk>/edit/', views.credit_rate_edit_view, name='credit_rate_edit'),
    path('credits/purchase-rates/<uuid:pk>/delete/', views.credit_rate_delete_view, name='credit_rate_delete'),
    path('credits/purchase-rates/<uuid:pk>/enable/', views.credit_rate_enable_view, name='credit_rate_enable'),
    path('credits/purchase-rates/<uuid:pk>/disable/', views.credit_rate_disable_view, name='credit_rate_disable'),

    path('credit-engine/coupons/', views.credit_coupons_list_view, name='credit_coupons'),
    path('credit-engine/coupons/create/', views.credit_coupon_create_view, name='credit_coupon_create'),
    path('credit-engine/coupons/<uuid:pk>/', views.credit_coupon_detail_view, name='credit_coupon_detail'),
    path('credit-engine/coupons/<uuid:pk>/edit/', views.credit_coupon_edit_view, name='credit_coupon_edit'),
    path('credit-engine/coupons/<uuid:pk>/delete/', views.credit_coupon_delete_view, name='credit_coupon_delete'),
    path('credit-engine/coupons/<uuid:pk>/enable/', views.credit_coupon_enable_view, name='credit_coupon_enable'),
    path('credit-engine/coupons/<uuid:pk>/disable/', views.credit_coupon_disable_view, name='credit_coupon_disable'),

    # Infrastructure & Storage
    path('storage/', views.storage_control_view, name='storage_control'),
    path('storage/streaming/', views.storage_streaming_view, name='storage_streaming'),
    path('storage/processing/', views.storage_processing_view, name='storage_processing'),
    path('storage/rates/', views.storage_rates_view, name='storage_rates'),
    path('storage/events/', views.storage_events_view, name='storage_events'),
    path('storage/billing/', views.storage_billing_list_view, name='storage_billing_list'),
    path('storage/billing/<uuid:pk>/', views.storage_billing_detail_view, name='storage_billing_detail'),
    path('storage/billing/<uuid:pk>/retry/', views.storage_billing_retry_view, name='storage_billing_retry'),
    path('storage/<uuid:pk>/', views.academy_storage_detail_view, name='academy_storage_detail'),

    path('payments/', views.payments_list_view, name='payments_list'),
    path('payments/<uuid:pk>/', views.payment_detail_view, name='payment_detail'),
    path('payments/<uuid:pk>/refund/', views.payment_refund_view, name='payment_refund'),
    path('transactions/', views.transactions_list_view, name='transactions_list'),
    path('invoices/', views.invoices_list_view, name='invoices_list'),

    # Financial / Commerce
    path('fees/', views.fees_list_view, name='fees_list'),
    path('fees/<uuid:pk>/', views.fee_detail_view, name='fee_detail'),
    path('fees/<uuid:pk>/pay/', views.fee_pay_view, name='fee_pay'),

    path('credits/', views.wallets_list_view, name='credits_list'),
    path('credits/adjust/', views.wallet_adjust_view, name='wallet_adjust_global'),
    path('credits/<uuid:pk>/', views.wallet_detail_view, name='wallet_detail_direct'),
    path('credits/wallets/<uuid:pk>/', views.wallet_detail_view, name='wallet_detail'),
    path('credits/wallets/<uuid:pk>/adjust/', views.wallet_adjust_view, name='wallet_adjust'),
    path('credits/transactions/', views.credit_transactions_view, name='credit_transactions'),

    # Academy & Team
    path('websites/', views.website_builder_list_view, name='website_builder'),
    path('websites/<uuid:pk>/edit/', views.website_builder_edit_view, name='website_builder_edit'),

    path('super-admin-staff/', views.super_admin_staff_list_view, name='super_admin_staff_list'),
    path('super-admin-staff/create/', views.super_admin_staff_create_view, name='super_admin_staff_create'),
    path('super-admin-staff/<uuid:pk>/', views.super_admin_staff_detail_view, name='super_admin_staff_detail'),
    path('super-admin-staff/<uuid:pk>/edit/', views.super_admin_staff_edit_view, name='super_admin_staff_edit'),
    path('super-admin-staff/<uuid:pk>/permissions/', views.super_admin_staff_permissions_view, name='super_admin_staff_permissions'),
    path('super-admin-staff/<uuid:pk>/enable/', views.super_admin_staff_enable_view, name='super_admin_staff_enable'),
    path('super-admin-staff/<uuid:pk>/disable/', views.super_admin_staff_disable_view, name='super_admin_staff_disable'),
    path('super-admin-staff/<uuid:pk>/delete/', views.super_admin_staff_delete_view, name='super_admin_staff_delete'),

    path('roles/', views.roles_list_view, name='roles_list'),
    path('roles/create/', views.role_create_view, name='role_create'),
    path('roles/<uuid:pk>/', views.role_detail_view, name='role_detail'),
    path('roles/<uuid:pk>/edit/', views.role_edit_view, name='role_edit'),
    path('roles/<uuid:pk>/delete/', views.role_delete_view, name='role_delete'),
    path('permissions/', views.permissions_list_view, name='permissions_list'),

    # System & Help
    path('support/', views.support_tickets_list_view, name='support_tickets_list'),
    path('support/<uuid:pk>/', views.support_ticket_detail_view, name='support_ticket_detail'),
    path('support/<uuid:pk>/reply/', views.support_ticket_reply_view, name='support_ticket_reply'),

    path('audit-logs/', views.audit_logs_view, name='audit_logs'),
    path('settings/', views.global_settings_view, name='global_settings'),
    path('email-jobs/', views.email_jobs_view, name='email_jobs'),
    path('email-jobs/<uuid:pk>/retry/', views.email_job_retry_view, name='email_job_retry'),
    path('system/tasks/', views.system_tasks_view, name='system_tasks'),
]
