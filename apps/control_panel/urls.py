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
    path('academies/', views.academies_list_view, name='academy-list'),
    path('academies/create/', views.academy_create_view, name='academy_create'),
    path('academies/create/', views.academy_create_view, name='academy-create'),
    path('academies/<uuid:pk>/', views.academy_detail_view, name='academy_detail'),
    path('academies/<uuid:pk>/', views.academy_detail_view, name='academy-detail'),
    path('academies/<uuid:pk>/edit/', views.academy_edit_view, name='academy_edit'),
    path('academies/<uuid:pk>/edit/', views.academy_edit_view, name='academy-edit'),
    path('academies/<uuid:pk>/delete/', views.academy_delete_view, name='academy_delete'),
    path('academies/<uuid:pk>/delete/', views.academy_delete_view, name='academy-delete'),
    path('academies/<uuid:pk>/action/', views.academy_action_view, name='academy_action'),

    path('users/', views.users_list_view, name='users_list'),
    path('users/create/', views.user_create_view, name='user_create'),
    path('users/<uuid:pk>/', views.user_detail_view, name='user_detail'),
    path('users/<uuid:pk>/edit/', views.user_edit_view, name='user_edit'),
    path('users/<uuid:pk>/delete/', views.user_delete_view, name='user_delete'),
    path('users/<uuid:pk>/enable/', views.user_enable_view, name='user_enable'),
    path('users/<uuid:pk>/disable/', views.user_disable_view, name='user_disable'),

    path('users/', views.users_list_view, name='user-list'),
    path('users/create/', views.user_create_view, name='user-create'),
    path('users/<uuid:pk>/', views.user_detail_view, name='user-detail'),
    path('users/<uuid:pk>/edit/', views.user_edit_view, name='user-edit'),
    path('users/<uuid:pk>/delete/', views.user_delete_view, name='user-delete'),

    path('students/', views.students_list_view, name='students_list'),
    path('students/create/', views.student_create_view, name='student_create'),
    path('students/<uuid:pk>/', views.student_detail_view, name='student_detail'),
    path('students/<uuid:pk>/edit/', views.student_edit_view, name='student_edit'),
    path('students/<uuid:pk>/delete/', views.student_delete_view, name='student_delete'),
    path('students/<uuid:pk>/enable/', views.student_enable_view, name='student_enable'),
    path('students/<uuid:pk>/disable/', views.student_disable_view, name='student_disable'),

    path('students/', views.students_list_view, name='student-list'),
    path('students/create/', views.student_create_view, name='student-create'),
    path('students/<uuid:pk>/', views.student_detail_view, name='student-detail'),
    path('students/<uuid:pk>/edit/', views.student_edit_view, name='student-edit'),
    path('students/<uuid:pk>/delete/', views.student_delete_view, name='student-delete'),

    path('courses/', views.courses_list_view, name='courses_list'),
    path('courses/create/', views.course_create_view, name='course_create'),
    path('courses/<uuid:pk>/', views.course_detail_view, name='course_detail'),
    path('courses/<uuid:pk>/edit/', views.course_edit_view, name='course_edit'),
    path('courses/<uuid:pk>/delete/', views.course_delete_view, name='course_delete'),
    path('courses/<uuid:pk>/enable/', views.course_enable_view, name='course_enable'),
    path('courses/<uuid:pk>/disable/', views.course_disable_view, name='course_disable'),

    path('courses/', views.courses_list_view, name='course-list'),
    path('courses/create/', views.course_create_view, name='course-create'),
    path('courses/<uuid:pk>/', views.course_detail_view, name='course-detail'),
    path('courses/<uuid:pk>/edit/', views.course_edit_view, name='course-edit'),
    path('courses/<uuid:pk>/delete/', views.course_delete_view, name='course-delete'),

    path('academies/<uuid:pk>/courses/json/', views.academy_courses_json_view, name='academy_courses_json'),

    # Standalone enrollments redirect to students list
    path('enrollments/', views.enrollments_redirect_view, name='enrollments_list'),

    # Monetization
    path('plans/', views.plans_list_view, name='plans_list'),
    path('plans/create/', views.plan_create_view, name='plan_create'),
    path('plans/<uuid:pk>/', views.plan_detail_view, name='plan_detail'),
    path('plans/<uuid:pk>/edit/', views.plan_edit_view, name='plan_edit'),
    path('plans/<uuid:pk>/delete/', views.plan_delete_view, name='plan_delete'),
    path('plans/<uuid:pk>/enable/', views.plan_enable_view, name='plan_enable'),
    path('plans/<uuid:pk>/disable/', views.plan_disable_view, name='plan_disable'),

    path('plans/', views.plans_list_view, name='plan-list'),
    path('plans/create/', views.plan_create_view, name='plan-create'),
    path('plans/<uuid:pk>/', views.plan_detail_view, name='plan-detail'),
    path('plans/<uuid:pk>/edit/', views.plan_edit_view, name='plan-edit'),
    path('plans/<uuid:pk>/delete/', views.plan_delete_view, name='plan-delete'),

    path('subscriptions/', views.subscriptions_list_view, name='subscriptions_list'),
    path('subscriptions/<uuid:pk>/', views.subscription_detail_view, name='subscription_detail'),

    path('features/', views.features_redirect_view, name='features_list'),
    path('features/create/', views.features_redirect_view, name='feature_create'),
    path('features/<uuid:pk>/', views.features_redirect_view, name='feature_detail'),
    path('features/<uuid:pk>/edit/', views.features_redirect_view, name='feature_edit'),
    path('features/<uuid:pk>/delete/', views.features_redirect_view, name='feature_delete'),
    path('features/<uuid:pk>/enable/', views.features_redirect_view, name='feature_enable'),
    path('features/<uuid:pk>/disable/', views.features_redirect_view, name='feature_disable'),

    path('pricing/', views.pricing_rules_list_view, name='pricing_rules_list'),
    path('pricing/', views.pricing_rules_list_view, name='pricing_engine'),
    path('pricing/create/', views.pricing_rule_create_view, name='pricing_rule_create'),
    path('pricing/<uuid:pk>/', views.pricing_rule_detail_view, name='pricing_rule_detail'),
    path('pricing/<uuid:pk>/edit/', views.pricing_rule_edit_view, name='pricing_rule_edit'),
    path('pricing/<uuid:pk>/delete/', views.pricing_rule_delete_view, name='pricing_rule_delete'),
    path('pricing/<uuid:pk>/enable/', views.pricing_rule_enable_view, name='pricing_rule_enable'),
    path('pricing/<uuid:pk>/disable/', views.pricing_rule_disable_view, name='pricing_rule_disable'),

    path('credit-engine/', views.credits_overview_view, name='credit_engine'),
    path('credit-engine/rates/', views.credit_rates_view, name='credit_rates'),
    path('credit-engine/packages/', views.credit_packages_view, name='credit_packages'),
    path('credit-engine/coupons/', views.credit_coupons_view, name='credit_coupons'),

    # Infrastructure
    path('storage/', views.storage_control_view, name='storage_control'),
    path('storage/<uuid:pk>/', views.academy_storage_detail_view, name='academy_storage_detail'),
    path('storage/config/', views.storage_config_view, name='storage_config'),
    path('usage/', views.usage_redirect_view, name='usage_metering'),
    path('media/', views.media_library_view, name='media_library'),

    path('payments/', views.payments_list_view, name='payments_list'),
    path('payments/<uuid:pk>/', views.payment_detail_view, name='payment_detail'),
    path('payments/<uuid:pk>/refund/', views.payment_refund_view, name='payment_refund'),
    path('transactions/', views.transactions_list_view, name='transactions_list'),
    path('invoices/', views.invoices_list_view, name='invoices_list'),

    # Financial / Commerce
    path('fees/', views.fees_list_view, name='fees_list'),
    path('fees/<uuid:pk>/', views.fee_detail_view, name='fee_detail'),
    path('fees/<uuid:pk>/pay/', views.fee_pay_view, name='fee_pay'),

    path('coupons/', views.coupons_list_view, name='coupons_list'),
    path('coupons/create/', views.coupon_create_view, name='coupon_create'),

    path('credits/', views.wallets_list_view, name='credits_list'),
    path('credits/adjust/', views.wallet_adjust_view, name='wallet_adjust_global'),
    path('credits/<uuid:pk>/', views.wallet_detail_view, name='wallet_detail_direct'),
    path('credits/wallets/<uuid:pk>/', views.wallet_detail_view, name='wallet_detail'),
    path('credits/wallets/<uuid:pk>/adjust/', views.wallet_adjust_view, name='wallet_adjust'),
    path('credits/transactions/', views.credit_transactions_view, name='credit_transactions'),

    # Academy & Team
    path('websites/', views.website_builder_list_view, name='website_builder'),
    path('websites/<uuid:pk>/edit/', views.website_builder_edit_view, name='website_builder_edit'),

    path('staff/', views.staff_list_view, name='staff_list'),
    path('staff/create/', views.staff_create_view, name='staff_create'),

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

    path('system/', views.system_health_view, name='system_health'),
    path('jobs/', views.background_jobs_view, name='background_jobs'),
    path('audit-logs/', views.audit_logs_view, name='audit_logs'),
    path('settings/', views.global_settings_view, name='global_settings'),
]
