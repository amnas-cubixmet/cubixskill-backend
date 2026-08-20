from django.urls import path
try:
    from . import views
except (ImportError, ValueError):
    from control_panel import views

app_name = 'control_panel'

urlpatterns = [
    # Auth
    path('login/', views.control_login_view, name='login'),
    path('logout/', views.control_logout_view, name='logout'),

    # Core Dashboard
    path('', views.dashboard_view, name='index'),
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # Academies
    path('academies/', views.academies_list_view, name='academies_list'),
    path('academies/<uuid:pk>/', views.academy_detail_view, name='academy_detail'),
    path('academies/<uuid:pk>/action/', views.academy_action_view, name='academy_action'),

    # Users & Students
    path('users/', views.users_list_view, name='users_list'),
    path('students/', views.students_list_view, name='students_list'),

    # Courses & Enrollments
    path('courses/', views.courses_list_view, name='courses_list'),
    path('enrollments/', views.enrollments_list_view, name='enrollments_list'),

    # Plans & Features
    path('plans/', views.plans_list_view, name='plans_list'),
    path('features/', views.features_list_view, name='features_list'),
    path('features/<uuid:pk>/edit/', views.feature_edit_view, name='feature_edit'),
    path('entitlements/', views.entitlements_list_view, name='entitlements_list'),

    # Pricing & Credits
    path('pricing/', views.pricing_engine_view, name='pricing_engine'),
    path('credits/', views.credits_overview_view, name='credits_overview'),

    # Storage & Metering
    path('storage/', views.storage_control_view, name='storage_control'),
    path('storage/config/', views.storage_config_view, name='storage_config'),
    path('usage/', views.usage_metering_view, name='usage_metering'),

    # Payments & Transactions
    path('payments/', views.payments_list_view, name='payments_list'),
    path('transactions/', views.transactions_list_view, name='transactions_list'),
    path('invoices/', views.invoices_list_view, name='invoices_list'),

    # System & Health
    path('system/', views.system_health_view, name='system_health'),
    path('jobs/', views.background_jobs_view, name='background_jobs'),

    # Audit & Security
    path('audit-logs/', views.audit_logs_view, name='audit_logs'),

    # Global Settings
    path('settings/', views.global_settings_view, name='global_settings'),
]
