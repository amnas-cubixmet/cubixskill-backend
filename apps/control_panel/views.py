import os
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.core.paginator import Paginator

from users_roles.models import User, SystemRoleCode
from academy.models import Academy, AcademyStatus
from courses.models import Course
from students.models import StudentProfile
from enrollments.models import Enrollment
from storage.models import MediaFile, AcademyStorageAccount
from credits.models import CreditAccount, CreditLedgerEntry, CreditSourceType, LedgerEntryType
from payments.models import PaymentOrder, PaymentTransaction, PaymentInvoice, OrderStatus
from plans_entitlements.models import Plan, AcademySubscription, PlanFeature
from audit_logs.models import AuditLog, AuditAction, AuditCategory

from .models import SystemSetting, FeatureDefinition, StorageBillingConfig, UsageSnapshot
from .decorators import super_admin_required

# --------------------------------------------------------------
# Authentication Views
# --------------------------------------------------------------

def control_login_view(request):
    if request.user.is_authenticated:
        is_super_admin = (
            getattr(request.user, 'role_code', '') in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF] or
            getattr(request.user, 'is_superuser', False)
        )
        if is_super_admin:
            return redirect('control_panel:dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()

        user = authenticate(request, email=email, password=password)
        if user and user.is_active:
            is_super_admin = (
                getattr(user, 'role_code', '') in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF] or
                getattr(user, 'is_superuser', False)
            )
            if is_super_admin:
                login(request, user)
                next_url = request.GET.get('next') or request.POST.get('next')
                if next_url and next_url.startswith('/'):
                    return redirect(next_url)
                return redirect('control_panel:dashboard')
            else:
                messages.error(request, "Access denied. Super Admin privileges required.")
        else:
            messages.error(request, "Invalid credentials or inactive account.")

    return render(request, 'control_panel/login.html')

def control_logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('control_panel:login')

# --------------------------------------------------------------
# Dashboard View
# --------------------------------------------------------------

@super_admin_required
def dashboard_view(request):
    now = timezone.now()

    # KPI Metrics
    total_academies = Academy.objects.count()
    active_academies = Academy.objects.filter(status=AcademyStatus.ACTIVE).count()
    demo_academies = Academy.objects.filter(is_demo=True).count()

    total_users = User.objects.count()
    total_students = StudentProfile.objects.count()
    total_courses = Course.objects.count()
    total_enrollments = Enrollment.objects.count()

    total_media_files = MediaFile.objects.count()
    total_storage_bytes = MediaFile.objects.aggregate(total=Sum('size_bytes'))['total'] or 0
    total_storage_gb = round(total_storage_bytes / (1024 * 1024 * 1024), 2)

    total_credits_issued = CreditLedgerEntry.objects.filter(entry_type=LedgerEntryType.CREDIT).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_credits_consumed = CreditLedgerEntry.objects.filter(entry_type=LedgerEntryType.DEBIT).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_revenue = PaymentOrder.objects.filter(status=OrderStatus.COMPLETED).aggregate(total=Sum('final_amount'))['total'] or Decimal('0.00')
    failed_payments = PaymentOrder.objects.filter(status=OrderStatus.FAILED).count()

    recent_academies = Academy.objects.order_by('-created_at')[:5]
    recent_audits = AuditLog.objects.select_related('actor', 'academy').order_by('-occurred_at')[:8]

    # Storage Billing Config
    storage_config = StorageBillingConfig.objects.first()
    if not storage_config:
        storage_config = StorageBillingConfig.objects.create()

    context = {
        'active_nav': 'dashboard',
        'total_academies': total_academies,
        'active_academies': active_academies,
        'demo_academies': demo_academies,
        'total_users': total_users,
        'total_students': total_students,
        'total_courses': total_courses,
        'total_enrollments': total_enrollments,
        'total_media_files': total_media_files,
        'total_storage_gb': total_storage_gb,
        'total_credits_issued': round(total_credits_issued, 2),
        'total_credits_consumed': round(total_credits_consumed, 2),
        'total_revenue': total_revenue,
        'failed_payments': failed_payments,
        'recent_academies': recent_academies,
        'recent_audits': recent_audits,
        'storage_config': storage_config,
    }
    return render(request, 'control_panel/dashboard.html', context)

# --------------------------------------------------------------
# Academies Management Views
# --------------------------------------------------------------

@super_admin_required
def academies_list_view(request):
    status_filter = request.GET.get('status', 'all')
    search_q = request.GET.get('q', '').strip()

    qs = Academy.objects.all()

    if status_filter == 'active':
        qs = qs.filter(status=AcademyStatus.ACTIVE)
    elif status_filter == 'suspended':
        qs = qs.filter(status=AcademyStatus.SUSPENDED)
    elif status_filter == 'demo':
        qs = qs.filter(is_demo=True)
    elif status_filter == 'inactive':
        qs = qs.filter(status=AcademyStatus.INACTIVE)

    if search_q:
        qs = qs.filter(Q(name__icontains=search_q) | Q(email__icontains=search_q) | Q(slug__icontains=search_q))

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    academies_page = paginator.get_page(page_number)

    context = {
        'active_nav': 'academies',
        'academies': academies_page,
        'status_filter': status_filter,
        'search_q': search_q,
    }
    return render(request, 'control_panel/academies/index.html', context)

@super_admin_required
def academy_detail_view(request, pk):
    academy = get_object_or_404(Academy, pk=pk)
    admin_user = User.objects.filter(academy=academy, role_code=SystemRoleCode.ACADEMY_ADMIN).first()
    students_count = StudentProfile.objects.filter(user__academy=academy).count()
    courses_count = Course.objects.filter(academy=academy).count()
    enrollments_count = Enrollment.objects.filter(course__academy=academy).count()

    media_bytes = MediaFile.objects.filter(academy_uuid=academy.id).aggregate(total=Sum('size_bytes'))['total'] or 0
    media_gb = round(media_bytes / (1024 * 1024 * 1024), 3)

    credit_account = getattr(academy, 'credit_account', None)
    if not credit_account:
        credit_account, _ = CreditAccount.objects.get_or_create(academy=academy)

    subscription = AcademySubscription.objects.filter(academy=academy).select_related('plan').first()
    plans = Plan.objects.all()
    recent_logs = AuditLog.objects.filter(academy=academy).order_by('-occurred_at')[:10]

    context = {
        'active_nav': 'academies',
        'academy': academy,
        'admin_user': admin_user,
        'students_count': students_count,
        'courses_count': courses_count,
        'enrollments_count': enrollments_count,
        'media_gb': media_gb,
        'credit_account': credit_account,
        'subscription': subscription,
        'plans': plans,
        'recent_logs': recent_logs,
    }
    return render(request, 'control_panel/academies/detail.html', context)

@super_admin_required
def academy_action_view(request, pk):
    academy = get_object_or_404(Academy, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        reason = request.POST.get('reason', 'Super Admin operation')

        if action == 'activate':
            academy.status = AcademyStatus.ACTIVE
            academy.save()
            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                academy=academy,
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.ACADEMY,
                target_type='Academy',
                target_id=str(academy.id),
                description=f"Activated Academy '{academy.name}'",
                changes={'status': {'before': 'SUSPENDED/INACTIVE', 'after': 'ACTIVE'}}
            )
            messages.success(request, f"Academy '{academy.name}' is now Active.")

        elif action == 'suspend':
            academy.status = AcademyStatus.SUSPENDED
            academy.save()
            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                academy=academy,
                action=AuditAction.ACADEMY_DISABLED,
                category=AuditCategory.ACADEMY,
                target_type='Academy',
                target_id=str(academy.id),
                description=f"Suspended Academy '{academy.name}'. Reason: {reason}",
                changes={'status': {'before': 'ACTIVE', 'after': 'SUSPENDED'}}
            )
            messages.warning(request, f"Academy '{academy.name}' has been Suspended.")

        elif action == 'toggle_demo':
            is_demo = request.POST.get('is_demo') == 'true'
            academy.is_demo = is_demo
            if is_demo:
                days = int(request.POST.get('demo_days', 14))
                academy.demo_start_date = timezone.now()
                academy.demo_expiry_date = timezone.now() + timezone.timedelta(days=days)
            academy.save()
            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                academy=academy,
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.ACADEMY,
                target_type='Academy',
                target_id=str(academy.id),
                description=f"Updated Demo status for '{academy.name}' to {is_demo}",
                changes={'is_demo': is_demo}
            )
            messages.success(request, f"Demo mode for '{academy.name}' updated.")

        elif action == 'adjust_credits':
            amount = Decimal(request.POST.get('amount', '0.00'))
            adj_type = request.POST.get('adjustment_type', 'ADD')
            
            credit_acc, _ = CreditAccount.objects.get_or_create(academy=academy)
            bal_before = credit_acc.balance

            if adj_type == 'ADD':
                credit_acc.balance += amount
                credit_acc.total_credited += amount
                entry_type = LedgerEntryType.CREDIT
            else:
                credit_acc.balance -= amount
                credit_acc.total_debited += amount
                entry_type = LedgerEntryType.DEBIT

            credit_acc.last_transaction_at = timezone.now()
            credit_acc.save()

            key = f"manual-adj-{academy.id}-{timezone.now().timestamp()}"
            entry = CreditLedgerEntry.objects.create(
                account=credit_acc,
                entry_type=entry_type,
                source_type=CreditSourceType.MANUAL_ADJUSTMENT,
                amount=amount,
                balance_before=bal_before,
                balance_after=credit_acc.balance,
                idempotency_key=key,
                description=f"Super Admin Adjustment: {reason}",
                created_by=request.user
            )

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                academy=academy,
                action=AuditAction.CREDIT_ADJUSTED,
                category=AuditCategory.CREDIT,
                target_type='CreditAccount',
                target_id=str(credit_acc.id),
                description=f"{adj_type} {amount} credits for '{academy.name}'. Reason: {reason}",
                changes={'balance': {'before': str(bal_before), 'after': str(credit_acc.balance)}}
            )
            messages.success(request, f"Adjusted {amount} credits for '{academy.name}'.")

    return redirect('control_panel:academy_detail', pk=pk)

# --------------------------------------------------------------
# Users & Students Views
# --------------------------------------------------------------

@super_admin_required
def users_list_view(request):
    q = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '')

    qs = User.objects.select_related('academy').all()

    if role_filter:
        qs = qs.filter(role_code=role_filter)
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(full_name__icontains=q))

    paginator = Paginator(qs, 20)
    users = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'users',
        'users': users,
        'q': q,
        'role_filter': role_filter,
    }
    return render(request, 'control_panel/users/index.html', context)

@super_admin_required
def students_list_view(request):
    q = request.GET.get('q', '').strip()
    qs = StudentProfile.objects.select_related('user', 'user__academy').all()

    if q:
        qs = qs.filter(Q(user__email__icontains=q) | Q(user__full_name__icontains=q) | Q(user__academy__name__icontains=q))

    paginator = Paginator(qs, 20)
    students = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'students',
        'students': students,
        'q': q,
    }
    return render(request, 'control_panel/students/index.html', context)

# --------------------------------------------------------------
# Courses & Enrollments Views
# --------------------------------------------------------------

@super_admin_required
def courses_list_view(request):
    q = request.GET.get('q', '').strip()
    qs = Course.objects.select_related('academy').all()

    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(academy__name__icontains=q))

    paginator = Paginator(qs, 20)
    courses = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'courses',
        'courses': courses,
        'q': q,
    }
    return render(request, 'control_panel/courses/index.html', context)

@super_admin_required
def enrollments_list_view(request):
    q = request.GET.get('q', '').strip()
    qs = Enrollment.objects.select_related('student__user', 'course__academy').all()

    if q:
        qs = qs.filter(Q(student__user__full_name__icontains=q) | Q(course__title__icontains=q))

    paginator = Paginator(qs, 20)
    enrollments = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'enrollments',
        'enrollments': enrollments,
        'q': q,
    }
    return render(request, 'control_panel/enrollments/index.html', context)

# --------------------------------------------------------------
# Plans & Features Views
# --------------------------------------------------------------

@super_admin_required
def plans_list_view(request):
    plans = Plan.objects.all()
    context = {
        'active_nav': 'plans',
        'plans': plans,
    }
    return render(request, 'control_panel/plans/index.html', context)

@super_admin_required
def features_list_view(request):
    features = FeatureDefinition.objects.all()
    context = {
        'active_nav': 'features',
        'features': features,
    }
    return render(request, 'control_panel/features/index.html', context)

@super_admin_required
def feature_edit_view(request, pk):
    feature = get_object_or_404(FeatureDefinition, pk=pk)

    if request.method == 'POST':
        feature.enabled_globally = request.POST.get('enabled_globally') == 'true'
        feature.is_billable = request.POST.get('is_billable') == 'true'
        feature.base_price = Decimal(request.POST.get('base_price', '0.00'))
        feature.billing_unit = request.POST.get('billing_unit', 'unit')
        feature.overage_price = Decimal(request.POST.get('overage_price', '0.00'))
        feature.save()

        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            action=AuditAction.ACADEMY_UPDATED,
            category=AuditCategory.SYSTEM,
            target_type='FeatureDefinition',
            target_id=str(feature.id),
            description=f"Updated global feature '{feature.name}' settings."
        )
        messages.success(request, f"Feature '{feature.name}' updated successfully.")
        return redirect('control_panel:features_list')

    return render(request, 'control_panel/features/edit.html', {'feature': feature, 'active_nav': 'features'})

@super_admin_required
def entitlements_list_view(request):
    entitlements = PlanFeature.objects.select_related('plan', 'feature').all()
    context = {
        'active_nav': 'entitlements',
        'entitlements': entitlements,
    }
    return render(request, 'control_panel/plans/entitlements.html', context)

# --------------------------------------------------------------
# Pricing & Credits Views
# --------------------------------------------------------------

@super_admin_required
def pricing_engine_view(request):
    features = FeatureDefinition.objects.all()

    if request.method == 'POST':
        for feat in features:
            bp_key = f"base_price_{feat.id}"
            op_key = f"overage_price_{feat.id}"
            if bp_key in request.POST:
                feat.base_price = Decimal(request.POST.get(bp_key, '0.00'))
            if op_key in request.POST:
                feat.overage_price = Decimal(request.POST.get(op_key, '0.00'))
            feat.save()

        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            action=AuditAction.ACADEMY_UPDATED,
            category=AuditCategory.SYSTEM,
            target_type='PricingEngine',
            target_id='global',
            description="Updated global pricing engine rates."
        )
        messages.success(request, "Global pricing engine rates saved.")
        return redirect('control_panel:pricing_engine')

    context = {
        'active_nav': 'pricing',
        'features': features,
    }
    return render(request, 'control_panel/pricing/index.html', context)

@super_admin_required
def credits_overview_view(request):
    accounts = CreditAccount.objects.select_related('academy').order_by('-balance')[:20]
    recent_entries = CreditLedgerEntry.objects.select_related('account__academy', 'created_by').order_by('-occurred_at')[:25]

    total_issued = CreditLedgerEntry.objects.filter(entry_type=LedgerEntryType.CREDIT).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_consumed = CreditLedgerEntry.objects.filter(entry_type=LedgerEntryType.DEBIT).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    context = {
        'active_nav': 'credits',
        'accounts': accounts,
        'recent_entries': recent_entries,
        'total_issued': round(total_issued, 2),
        'total_consumed': round(total_consumed, 2),
    }
    return render(request, 'control_panel/credits/index.html', context)

# --------------------------------------------------------------
# Storage & Metering Views
# --------------------------------------------------------------

@super_admin_required
def storage_control_view(request):
    storage_config = StorageBillingConfig.objects.first()
    if not storage_config:
        storage_config = StorageBillingConfig.objects.create()

    total_files = MediaFile.objects.count()
    images_count = MediaFile.objects.filter(media_type='IMAGE').count()
    videos_count = MediaFile.objects.filter(media_type='VIDEO').count()
    audios_count = MediaFile.objects.filter(media_type='AUDIO').count()
    docs_count = MediaFile.objects.filter(media_type='DOCUMENT').count()

    total_bytes = MediaFile.objects.aggregate(total=Sum('size_bytes'))['total'] or 0
    total_gb = round(total_bytes / (1024 * 1024 * 1024), 3)

    storage_accounts = AcademyStorageAccount.objects.all().order_by('-current_usage_bytes')[:15]

    context = {
        'active_nav': 'storage',
        'storage_config': storage_config,
        'total_files': total_files,
        'images_count': images_count,
        'videos_count': videos_count,
        'audios_count': audios_count,
        'docs_count': docs_count,
        'total_gb': total_gb,
        'storage_accounts': storage_accounts,
    }
    return render(request, 'control_panel/storage/index.html', context)

@super_admin_required
def storage_config_view(request):
    storage_config = StorageBillingConfig.objects.first()
    if not storage_config:
        storage_config = StorageBillingConfig.objects.create()

    if request.method == 'POST':
        storage_config.storage_unit = request.POST.get('storage_unit', 'GB')
        storage_config.metering_interval_hours = int(request.POST.get('metering_interval_hours', 12))
        storage_config.price_per_unit = Decimal(request.POST.get('price_per_unit', '0.50'))
        storage_config.rounding_method = request.POST.get('rounding_method', 'UP')
        storage_config.billing_enabled = request.POST.get('billing_enabled') == 'true'
        storage_config.save()

        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            action=AuditAction.STORAGE_CORRECTED,
            category=AuditCategory.STORAGE,
            target_type='StorageBillingConfig',
            target_id=str(storage_config.id),
            description=f"Updated storage billing rules: {storage_config.price_per_unit} per {storage_config.storage_unit} every {storage_config.metering_interval_hours}h."
        )
        messages.success(request, "Storage billing configuration updated.")
        return redirect('control_panel:storage_control')

    return redirect('control_panel:storage_control')

@super_admin_required
def usage_metering_view(request):
    snapshots = UsageSnapshot.objects.order_by('-recorded_at')[:30]
    context = {
        'active_nav': 'usage',
        'snapshots': snapshots,
    }
    return render(request, 'control_panel/usage/index.html', context)

# --------------------------------------------------------------
# Payments Views
# --------------------------------------------------------------

@super_admin_required
def payments_list_view(request):
    orders = PaymentOrder.objects.select_related('academy', 'payer', 'plan').order_by('-created_at')[:30]
    context = {
        'active_nav': 'payments',
        'orders': orders,
    }
    return render(request, 'control_panel/payments/index.html', context)

@super_admin_required
def transactions_list_view(request):
    transactions = PaymentTransaction.objects.select_related('order', 'payer').order_by('-initiated_at')[:30]
    context = {
        'active_nav': 'transactions',
        'transactions': transactions,
    }
    return render(request, 'control_panel/payments/transactions.html', context)

@super_admin_required
def invoices_list_view(request):
    invoices = PaymentInvoice.objects.select_related('order').order_by('-issued_at')[:30]
    context = {
        'active_nav': 'invoices',
        'invoices': invoices,
    }
    return render(request, 'control_panel/payments/invoices.html', context)

# --------------------------------------------------------------
# System Health & Background Jobs
# --------------------------------------------------------------

@super_admin_required
def system_health_view(request):
    db_status = "Healthy"
    try:
        User.objects.first()
    except Exception as e:
        db_status = f"Error: {str(e)}"

    storage_status = "Local File System"

    context = {
        'active_nav': 'system',
        'db_status': db_status,
        'storage_status': storage_status,
        'python_version': os.sys.version.split(' ')[0],
        'django_environment': 'Production' if not os.getenv('DEBUG', 'True').lower() in ('true', '1') else 'Development',
    }
    return render(request, 'control_panel/system/index.html', context)

@super_admin_required
def background_jobs_view(request):
    storage_config = StorageBillingConfig.objects.first()
    context = {
        'active_nav': 'jobs',
        'storage_config': storage_config,
    }
    return render(request, 'control_panel/system/jobs.html', context)

# --------------------------------------------------------------
# Audit Logs View
# --------------------------------------------------------------

@super_admin_required
def audit_logs_view(request):
    q = request.GET.get('q', '').strip()
    category_filter = request.GET.get('category', '')

    qs = AuditLog.objects.select_related('actor', 'academy').order_by('-occurred_at')

    if category_filter:
        qs = qs.filter(category=category_filter)
    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(actor_display__icontains=q) | Q(action__icontains=q))

    paginator = Paginator(qs, 30)
    audits = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'audit',
        'audits': audits,
        'q': q,
        'category_filter': category_filter,
    }
    return render(request, 'control_panel/audit/index.html', context)

# --------------------------------------------------------------
# Global Settings View
# --------------------------------------------------------------

@super_admin_required
def global_settings_view(request):
    if request.method == 'POST':
        for key in ['platform_name', 'support_email', 'default_currency', 'maintenance_mode']:
            if key in request.POST:
                setting, _ = SystemSetting.objects.get_or_create(key=key)
                setting.value = request.POST.get(key)
                setting.save()

        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            action=AuditAction.WEBSITE_SETTINGS_CHANGED,
            category=AuditCategory.SYSTEM,
            target_type='SystemSetting',
            target_id='global',
            description="Updated platform global settings."
        )
        messages.success(request, "Global system settings saved.")
        return redirect('control_panel:global_settings')

    settings_dict = {s.key: s.value for s in SystemSetting.objects.all()}
    context = {
        'active_nav': 'settings',
        'settings': settings_dict,
    }
    return render(request, 'control_panel/settings/index.html', context)
