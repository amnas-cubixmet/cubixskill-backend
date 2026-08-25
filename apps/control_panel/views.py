import os
from decimal import Decimal
from urllib.parse import urlparse, parse_qs
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Sum, Q, Count
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.core.paginator import Paginator
from django.utils.text import slugify
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import HttpResponseForbidden, JsonResponse
from django.conf import settings
from users_roles.models import User, SystemRoleCode, Role, Permission, RolePermission, UserPermissionOverride, RoleScope, ensure_default_permissions_seeded, get_user_permissions, has_permission
from academy.models import Academy, AcademyStatus
from courses.models import Course, CourseCategory, CourseModule, CourseStatus, CourseLevel
from students.models import StudentProfile
from enrollments.models import Enrollment, EnrollmentStatus, EnrollmentSource
from storage.models import MediaFile, AcademyStorageAccount
from credits.models import CreditAccount, CreditLedgerEntry, CreditRate, CreditPackage, CreditPurchaseCoupon, CreditSourceType, LedgerEntryType, CreditAccountStatus
from credits.services import CreditsService
from payments.models import PaymentOrder, PaymentTransaction, PaymentRefund, PaymentInvoice, OrderStatus
from plans_entitlements.models import Plan, AcademySubscription, PlanFeature
from audit_logs.models import AuditLog, AuditAction, AuditCategory
from fees.models import StudentFeeAccount, FeeInstallment, FeePayment, FeeAdjustment
from fees.services import FeeCollectionService
from enrollments.services import EnrollmentService

from .models import SystemSetting, FeatureDefinition, PricingRule, StorageBillingConfig, UsageSnapshot, SupportTicket, TicketMessage, AcademyWebsiteConfig, TicketStatus, TicketPriority
from .decorators import super_admin_required

# --------------------------------------------------------------
# Authentication Views
# --------------------------------------------------------------

def legacy_control_login_redirect(request):
    """
    302 redirect from legacy /control/login/ to canonical /login/ preserving next parameter safely.
    """
    next_param = request.GET.get('next', '')
    login_url = settings.LOGIN_URL
    if next_param:
        if '/control/login/' in next_param or '/login/' in next_param:
            parsed = urlparse(next_param)
            qs = parse_qs(parsed.query)
            if 'next' in qs and qs['next']:
                next_param = qs['next'][0]
            else:
                next_param = '/'
        return redirect(f"{login_url}?next={next_param}")
    return redirect(login_url)

def control_login_view(request):
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if next_url and ('/login/' in next_url or '/control/login/' in next_url):
        next_url = ''

    if request.user.is_authenticated:
        is_super_admin = (
            getattr(request.user, 'role_code', '') in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF] or
            getattr(request.user, 'is_superuser', False)
        )
        if is_super_admin:
            if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('control_panel:dashboard')
        else:
            return HttpResponseForbidden("Access Denied: Super Admin privileges required.")

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
                if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect('control_panel:dashboard')
            else:
                return HttpResponseForbidden("Access Denied: Super Admin privileges required.")
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, 'control_panel/login.html', {'next': next_url})

def control_logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect(settings.LOGIN_URL)

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
        qs = qs.filter(
            Q(name__icontains=search_q) |
            Q(email__icontains=search_q) |
            Q(slug__icontains=search_q) |
            Q(phone__icontains=search_q)
        )

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
def academy_create_view(request):
    errors = {}
    form_data = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        slug_input = request.POST.get('slug', '').strip()
        admin_email = request.POST.get('admin_email', '').strip()
        admin_name = request.POST.get('admin_name', '').strip()
        is_demo = request.POST.get('is_demo') == 'true'
        status = request.POST.get('status', AcademyStatus.ACTIVE)

        form_data = {
            'name': name,
            'email': email,
            'phone': phone,
            'slug': slug_input,
            'admin_email': admin_email,
            'admin_name': admin_name,
            'is_demo': is_demo,
            'status': status,
        }

        # Server-side validation
        if not name:
            errors['name'] = "Academy name is required."
        if not email:
            errors['email'] = "Academy email is required."
        if not admin_email:
            errors['admin_email'] = "Admin email is required."

        # Slug validation
        slug = slug_input or slugify(name)
        if slug and Academy.objects.filter(slug=slug).exists():
            errors['slug'] = f"The slug '{slug}' is already taken. Please choose another."

        if not errors:
            from django.db import transaction
            with transaction.atomic():
                academy = Academy.objects.create(
                    name=name,
                    email=email,
                    phone=phone,
                    slug=slug,
                    status=status,
                    is_demo=is_demo
                )
                
                # Initial Admin user
                admin_user, _ = User.objects.get_or_create(
                    email=admin_email,
                    defaults={
                        'full_name': admin_name or f"{name} Owner",
                        'academy': academy,
                        'role_code': SystemRoleCode.ACADEMY_ADMIN,
                        'is_staff': True,
                    }
                )
                admin_user.set_password('Password123!')
                admin_user.save()

                # Initialize Wallet & Storage Account
                CreditsService.get_or_create_account(academy)
                AcademyStorageAccount.objects.get_or_create(academy_uuid=academy.id)

                AuditLog.objects.create(
                    actor=request.user,
                    actor_type='SUPER_ADMIN',
                    academy=academy,
                    action=AuditAction.ACADEMY_CREATED,
                    category=AuditCategory.ACADEMY,
                    target_type='Academy',
                    target_id=str(academy.id),
                    description=f"Created Academy '{name}' with owner {admin_email}."
                )

                messages.success(request, f"Academy '{name}' created successfully.")
                return redirect('control_panel:academy_detail', pk=academy.id)

    return render(request, 'control_panel/academies/create.html', {
        'active_nav': 'academies',
        'errors': errors,
        'form_data': form_data,
        'statuses': AcademyStatus.choices,
    })

@super_admin_required
def academy_detail_view(request, pk):
    academy = get_object_or_404(Academy, pk=pk)
    admin_user = User.objects.filter(academy=academy, role_code=SystemRoleCode.ACADEMY_ADMIN).first()
    students_count = StudentProfile.objects.filter(user__academy=academy).count()
    courses_count = Course.objects.filter(academy=academy).count()
    enrollments_count = Enrollment.objects.filter(course__academy=academy).count()

    media_bytes = MediaFile.objects.filter(academy_uuid=academy.id).aggregate(total=Sum('size_bytes'))['total'] or 0
    media_gb = round(media_bytes / (1024 * 1024 * 1024), 3)

    credit_account = CreditsService.get_or_create_account(academy)
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
def academy_edit_view(request, pk):
    academy = get_object_or_404(Academy, pk=pk)
    errors = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        slug_input = request.POST.get('slug', '').strip()
        status = request.POST.get('status', academy.status)
        is_demo = request.POST.get('is_demo') == 'true'

        if not name:
            errors['name'] = "Academy name cannot be empty."
        if not email:
            errors['email'] = "Academy email cannot be empty."

        slug = slug_input or slugify(name)
        if slug and Academy.objects.filter(slug=slug).exclude(pk=pk).exists():
            errors['slug'] = f"The slug '{slug}' is taken by another academy."

        if not errors:
            academy.name = name
            academy.email = email
            academy.phone = phone
            academy.slug = slug
            academy.status = status
            academy.is_demo = is_demo
            academy.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                academy=academy,
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.ACADEMY,
                target_type='Academy',
                target_id=str(academy.id),
                description=f"Updated details for Academy '{academy.name}'."
            )
            messages.success(request, f"Academy '{academy.name}' updated successfully.")
            return redirect('control_panel:academy_detail', pk=pk)

    return render(request, 'control_panel/academies/edit.html', {
        'academy': academy,
        'errors': errors,
        'statuses': AcademyStatus.choices,
        'active_nav': 'academies',
    })

@super_admin_required
def academy_delete_view(request, pk):
    academy = get_object_or_404(Academy, pk=pk)
    students_count = StudentProfile.objects.filter(user__academy=academy).count()
    courses_count = Course.objects.filter(academy=academy).count()
    enrollments_count = Enrollment.objects.filter(course__academy=academy).count()

    if request.method == 'POST':
        name = academy.name
        from django.db import transaction
        with transaction.atomic():
            # Soft-delete/deactivate or delete safely
            academy.status = AcademyStatus.INACTIVE
            academy.is_active = False
            academy.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.ACADEMY_DISABLED,
                category=AuditCategory.ACADEMY,
                target_type='Academy',
                target_id=str(pk),
                description=f"Deactivated/Deleted Academy '{name}'."
            )

            messages.success(request, f"Academy '{name}' has been deactivated successfully.")
            return redirect('control_panel:academies_list')

    return render(request, 'control_panel/academies/confirm_delete.html', {
        'academy': academy,
        'students_count': students_count,
        'courses_count': courses_count,
        'enrollments_count': enrollments_count,
        'active_nav': 'academies',
    })

@super_admin_required
def academy_action_view(request, pk):
    academy = get_object_or_404(Academy, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        reason = request.POST.get('reason', 'Super Admin operation')

        if action == 'activate':
            academy.status = AcademyStatus.ACTIVE
            academy.save()
            messages.success(request, f"Academy '{academy.name}' is now Active.")
        elif action == 'suspend':
            academy.status = AcademyStatus.SUSPENDED
            academy.save()
            messages.warning(request, f"Academy '{academy.name}' has been Suspended.")

    return redirect('control_panel:academy_detail', pk=pk)

# --------------------------------------------------------------
# Users & Staff Views
# --------------------------------------------------------------

@super_admin_required
def enrollments_redirect_view(request):
    return redirect('control_panel:students_list')

HUMAN_ROLE_LABELS = {
    SystemRoleCode.SUPER_ADMIN: 'Super Admin',
    SystemRoleCode.SUPER_ADMIN_STAFF: 'Super Admin Staff',
    SystemRoleCode.ACADEMY_ADMIN: 'Academy Admin',
    SystemRoleCode.ACADEMY_STAFF: 'Academy Staff',
    SystemRoleCode.STUDENT: 'Student',
}

@super_admin_required
def users_list_view(request):
    q = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    status_filter = request.GET.get('status', '').strip()
    academy_id = request.GET.get('academy', '').strip()

    qs = User.objects.select_related('academy', 'assigned_role').all().order_by('-created_at')

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
        if request.user.academy:
            qs = qs.filter(academy=request.user.academy)
        else:
            qs = qs.none()
    elif academy_id:
        qs = qs.filter(academy_id=academy_id)

    if role_filter:
        qs = qs.filter(role_code=role_filter)
    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(full_name__icontains=q) | Q(phone__icontains=q))

    total_users = qs.count()
    active_users = qs.filter(is_active=True).count()
    inactive_users = qs.filter(is_active=False).count()
    staff_users = qs.filter(role_code__in=[SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF, SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]).count()

    paginator = Paginator(qs, 20)
    users_page = paginator.get_page(request.GET.get('page'))

    users_data = []
    for u in users_page:
        users_data.append({
            'user': u,
            'role_label': HUMAN_ROLE_LABELS.get(u.role_code, u.role_code),
        })

    academies = Academy.objects.all().order_by('name')

    context = {
        'active_nav': 'users',
        'users_data': users_data,
        'users_page': users_page,
        'academies': academies,
        'q': q,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'selected_academy': academy_id,
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'staff_users': staff_users,
        'roles': SystemRoleCode.choices,
    }
    return render(request, 'control_panel/users/index.html', context)

@super_admin_required
def user_create_view(request):
    errors = {}
    form_data = {}
    academies = Academy.objects.all().order_by('name')

    allowed_roles = list(SystemRoleCode.choices)
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser):
        allowed_roles = [r for r in allowed_roles if r[0] not in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]]

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        role_code = request.POST.get('role_code', SystemRoleCode.STUDENT)
        academy_id = request.POST.get('academy_id')
        is_active = request.POST.get('is_active') == 'true'

        form_data = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'role_code': role_code,
            'academy_id': academy_id,
            'is_active': is_active,
        }

        if not full_name:
            errors['full_name'] = "Full Name is required."
        if not email:
            errors['email'] = "Email Address is required."
        elif User.objects.filter(email__iexact=email).exists():
            errors['email'] = "A user account with this email address already exists."

        if role_code == SystemRoleCode.SUPER_ADMIN and not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser):
            errors['role_code'] = "You do not have permission to create primary Super Admin accounts."

        academy = Academy.objects.filter(pk=academy_id).first() if academy_id else None
        if role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF] and not academy:
            errors['academy_id'] = "Academy selection is required for Academy Admin / Staff roles."

        if not errors:
            from django.db import transaction
            with transaction.atomic():
                user = User.objects.create_user(
                    email=email,
                    password='Password123!',
                    full_name=full_name,
                    phone=phone,
                    role_code=role_code,
                    academy=academy,
                    is_active=is_active,
                    is_staff=(role_code != SystemRoleCode.STUDENT)
                )

                AuditLog.objects.create(
                    actor=request.user,
                    actor_type='ADMIN',
                    academy=academy,
                    action=AuditAction.USER_CREATED,
                    category=AuditCategory.USER,
                    target_type='User',
                    target_id=str(user.id),
                    description=f"Created user account for '{user.email}' with role '{role_code}'."
                )

                messages.success(request, f"User account '{user.email}' created successfully.")
                return redirect('control_panel:user_detail', pk=user.id)

    return render(request, 'control_panel/users/create.html', {
        'active_nav': 'users',
        'academies': academies,
        'roles': allowed_roles,
        'errors': errors,
        'form_data': form_data,
    })

@super_admin_required
def user_detail_view(request, pk):
    target_user = get_object_or_404(User.objects.select_related('academy', 'assigned_role'), pk=pk)

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
        if request.user.academy and target_user.academy != request.user.academy:
            return HttpResponseForbidden("Access Denied.")

    role_label = HUMAN_ROLE_LABELS.get(target_user.role_code, target_user.role_code)
    recent_logs = AuditLog.objects.filter(target_id=str(pk)).order_by('-occurred_at')[:10]

    context = {
        'active_nav': 'users',
        'target_user': target_user,
        'role_label': role_label,
        'recent_logs': recent_logs,
    }
    return render(request, 'control_panel/users/detail.html', context)

@super_admin_required
def user_edit_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)

    if target_user.role_code == SystemRoleCode.SUPER_ADMIN and not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser):
        messages.error(request, "Primary Super Admin account cannot be modified by staff.")
        return redirect('control_panel:users_list')

    errors = {}
    academies = Academy.objects.all().order_by('name')
    allowed_roles = list(SystemRoleCode.choices)

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        role_code = request.POST.get('role_code', target_user.role_code)
        academy_id = request.POST.get('academy_id')
        is_active = request.POST.get('is_active') == 'true'

        if not full_name:
            errors['full_name'] = "Full Name cannot be empty."

        academy = Academy.objects.filter(pk=academy_id).first() if academy_id else None

        if not errors:
            target_user.full_name = full_name
            target_user.phone = phone
            if request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser:
                target_user.role_code = role_code
            if academy:
                target_user.academy = academy
            target_user.is_active = is_active
            target_user.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='ADMIN',
                academy=target_user.academy,
                action=AuditAction.USER_ROLE_CHANGED,
                category=AuditCategory.USER,
                target_type='User',
                target_id=str(target_user.id),
                description=f"Updated profile for user '{target_user.email}'."
            )

            messages.success(request, f"Updated profile for user '{target_user.email}'.")
            return redirect('control_panel:user_detail', pk=pk)

    return render(request, 'control_panel/users/edit.html', {
        'active_nav': 'users',
        'target_user': target_user,
        'academies': academies,
        'roles': allowed_roles,
        'errors': errors,
    })

@super_admin_required
def user_enable_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        target_user.is_active = True
        target_user.save()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='ADMIN',
            action=AuditAction.USER_ACTIVATED,
            category=AuditCategory.USER,
            target_type='User',
            target_id=str(pk),
            description=f"Enabled user account '{target_user.email}'."
        )
        messages.success(request, f"User '{target_user.email}' enabled successfully.")
    return redirect('control_panel:users_list')

@super_admin_required
def user_disable_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if target_user.role_code == SystemRoleCode.SUPER_ADMIN:
        messages.error(request, "Primary Super Admin account cannot be disabled.")
        return redirect('control_panel:users_list')

    if request.method == 'POST':
        target_user.is_active = False
        target_user.save()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='ADMIN',
            action=AuditAction.USER_DEACTIVATED,
            category=AuditCategory.USER,
            target_type='User',
            target_id=str(pk),
            description=f"Disabled user account '{target_user.email}'."
        )
        messages.warning(request, f"User '{target_user.email}' disabled.")
    return redirect('control_panel:users_list')

@super_admin_required
def user_delete_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if target_user.role_code == SystemRoleCode.SUPER_ADMIN:
        messages.error(request, "Primary Super Admin account cannot be deleted.")
        return redirect('control_panel:users_list')

    if request.method == 'POST':
        email = target_user.email
        target_user.delete()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='ADMIN',
            action=AuditAction.USER_DEACTIVATED,
            category=AuditCategory.USER,
            target_type='User',
            target_id=str(pk),
            description=f"Deleted user account '{email}'."
        )
        messages.success(request, f"User account '{email}' deleted.")
        return redirect('control_panel:users_list')

    return render(request, 'control_panel/users/confirm_delete.html', {
        'active_nav': 'users',
        'target_user': target_user,
    })

# --------------------------------------------------------------
# Students Views
# --------------------------------------------------------------

@super_admin_required
def students_list_view(request):
    q = request.GET.get('q', '').strip()
    academy_id = request.GET.get('academy', '').strip()
    status_filter = request.GET.get('status', 'all').strip()

    qs = (
        User.objects.filter(Q(role_code=SystemRoleCode.STUDENT) | Q(student_profile__isnull=False))
        .distinct()
        .select_related('academy', 'student_profile')
        .annotate(courses_count=Count('enrollments', distinct=True))
        .order_by('-created_at')
    )

    # Tenant restriction for Academy-level users
    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
        if request.user.academy:
            qs = qs.filter(academy=request.user.academy)
        else:
            qs = qs.none()
    elif academy_id:
        qs = qs.filter(academy_id=academy_id)

    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    if q:
        qs = qs.filter(
            Q(full_name__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q)
            | Q(student_profile__student_code__icontains=q)
            | Q(student_profile__display_name__icontains=q)
        )

    # Summary KPI cards
    total_students = qs.count()
    active_students = qs.filter(is_active=True).count()
    inactive_students = qs.filter(is_active=False).count()
    enrolled_students = Enrollment.objects.filter(student__in=qs).values('student').distinct().count()

    paginator = Paginator(qs, 20)
    students_page = paginator.get_page(request.GET.get('page'))

    students_data = []
    for u in students_page:
        students_data.append({
            'user': u,
            'courses_count': getattr(u, 'courses_count', 0),
        })

    academies = Academy.objects.all().order_by('name')

    context = {
        'active_nav': 'students',
        'students_data': students_data,
        'students_page': students_page,
        'academies': academies,
        'q': q,
        'selected_academy': academy_id,
        'status_filter': status_filter,
        'total_students': total_students,
        'active_students': active_students,
        'inactive_students': inactive_students,
        'enrolled_students': enrolled_students,
    }
    return render(request, 'control_panel/students/index.html', context)

@super_admin_required
def academy_courses_json_view(request, pk):
    academy = get_object_or_404(Academy, pk=pk)
    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF] and request.user.academy:
        if academy != request.user.academy:
            return JsonResponse({'courses': [], 'error': 'Forbidden'}, status=403)
            
    courses = Course.objects.filter(academy=academy, is_active=True).select_related('category').order_by('title')
    data = []
    for c in courses:
        modules_count = c.modules.count() if hasattr(c, 'modules') else 0
        data.append({
            'id': str(c.id),
            'title': c.title,
            'category': c.category.name if c.category else 'General',
            'level': c.get_level_display() if hasattr(c, 'get_level_display') else c.level,
            'price': f"₹{c.price}" if not c.is_free else "Free",
            'status': c.get_status_display() if hasattr(c, 'get_status_display') else c.status,
            'is_free': c.is_free,
            'modules_count': modules_count
        })
    return JsonResponse({'courses': data})

@super_admin_required
def student_create_view(request):
    errors = {}
    form_data = {}
    academies = Academy.objects.all().order_by('name')

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF] and request.user.academy:
        academies = Academy.objects.filter(id=request.user.academy.id)

    academy_courses_map = {}
    for aca in academies:
        courses = Course.objects.filter(academy=aca, is_active=True).select_related('category').order_by('title')
        c_list = []
        for c in courses:
            c_list.append({
                'id': str(c.id),
                'title': c.title,
                'category': c.category.name if c.category else 'General',
                'level': c.get_level_display() if hasattr(c, 'get_level_display') else c.level,
                'price': f"₹{c.price}" if not c.is_free else "Free",
                'status': c.get_status_display() if hasattr(c, 'get_status_display') else c.status,
                'is_free': c.is_free,
            })
        academy_courses_map[str(aca.id)] = c_list

    selected_course_ids = []

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        academy_id = request.POST.get('academy_id')
        is_active = request.POST.get('is_active') == 'true'
        selected_course_ids = request.POST.getlist('course_ids')

        form_data = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'academy_id': academy_id,
            'is_active': is_active,
        }

        if not full_name:
            errors['full_name'] = "Full Name is required."
        if not email:
            errors['email'] = "Email Address is required."

        academy = None
        if academy_id:
            academy = Academy.objects.filter(pk=academy_id).first()

        existing_user = User.objects.filter(email=email).first()
        if existing_user:
            if existing_user.role_code != SystemRoleCode.STUDENT:
                errors['email'] = f"A platform user with this email already exists with role '{existing_user.role_code}'."
            elif academy and existing_user.academy == academy:
                errors['email'] = "This student is already registered with the selected academy."

        valid_courses = []
        if selected_course_ids and academy:
            valid_courses = list(Course.objects.filter(pk__in=selected_course_ids, academy=academy))
            if len(valid_courses) != len(set(selected_course_ids)):
                errors['courses'] = "One or more selected courses do not belong to the selected academy."

        if not errors:
            from django.db import transaction
            with transaction.atomic():
                if existing_user:
                    user = existing_user
                    if academy and not user.academy:
                        user.academy = academy
                        user.save()
                    messages.info(request, f"Existing student user '{email}' linked to academy.")
                else:
                    user = User.objects.create_user(
                        email=email,
                        password='Password123!',
                        full_name=full_name,
                        phone=phone,
                        academy=academy,
                        role_code=SystemRoleCode.STUDENT,
                        is_active=is_active
                    )
                    messages.success(request, f"Student '{email}' created successfully.")

                for crs in valid_courses:
                    Enrollment.objects.get_or_create(
                        student=user,
                        course=crs,
                        defaults={
                            'status': EnrollmentStatus.ACTIVE,
                            'source': EnrollmentSource.MANUAL,
                            'created_by': request.user
                        }
                    )

                AuditLog.objects.create(
                    actor=request.user,
                    actor_type='ADMIN',
                    academy=user.academy,
                    action=AuditAction.USER_CREATED,
                    category=AuditCategory.STUDENT,
                    target_type='User',
                    target_id=str(user.id),
                    description=f"Created student account for '{user.email}' with {len(valid_courses)} course enrollments."
                )

                return redirect('control_panel:student_detail', pk=user.id)

    return render(request, 'control_panel/students/create.html', {
        'active_nav': 'students',
        'academies': academies,
        'academy_courses_map': academy_courses_map,
        'selected_course_ids': selected_course_ids,
        'errors': errors,
        'form_data': form_data,
    })

@super_admin_required
def student_detail_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
        if request.user.academy and target_user.academy != request.user.academy:
            return HttpResponseForbidden("Access Denied: You cannot view students of another academy.")

    enrollments = Enrollment.objects.filter(student=target_user).select_related('course', 'course__academy', 'course__category')
    recent_logs = AuditLog.objects.filter(target_id=str(pk)).order_by('-occurred_at')[:10]

    context = {
        'active_nav': 'students',
        'target_user': target_user,
        'enrollments': enrollments,
        'recent_logs': recent_logs,
    }
    return render(request, 'control_panel/students/detail.html', context)

@super_admin_required
def student_edit_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
        if request.user.academy and target_user.academy != request.user.academy:
            return HttpResponseForbidden("Access Denied.")

    errors = {}
    academies = Academy.objects.all().order_by('name')

    existing_enrollments = Enrollment.objects.filter(student=target_user).select_related('course')
    enrolled_course_ids = set(str(e.course_id) for e in existing_enrollments if e.course_id)

    academy_courses_map = {}
    for aca in academies:
        courses = Course.objects.filter(academy=aca, is_active=True).select_related('category').order_by('title')
        c_list = []
        for c in courses:
            c_list.append({
                'id': str(c.id),
                'title': c.title,
                'category': c.category.name if c.category else 'General',
                'level': c.get_level_display() if hasattr(c, 'get_level_display') else c.level,
                'price': f"₹{c.price}" if not c.is_free else "Free",
                'status': c.get_status_display() if hasattr(c, 'get_status_display') else c.status,
                'is_free': c.is_free,
            })
        academy_courses_map[str(aca.id)] = c_list

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        academy_id = request.POST.get('academy_id')
        is_active = request.POST.get('is_active') == 'true'
        selected_course_ids = set(request.POST.getlist('course_ids'))

        if not full_name:
            errors['full_name'] = "Full Name cannot be empty."

        academy = Academy.objects.filter(pk=academy_id).first() if academy_id else target_user.academy

        if not errors:
            from django.db import transaction
            with transaction.atomic():
                target_user.full_name = full_name
                target_user.phone = phone
                if academy:
                    target_user.academy = academy
                target_user.is_active = is_active
                target_user.save()

                for crs_id in selected_course_ids:
                    crs = Course.objects.filter(pk=crs_id, academy=academy).first()
                    if crs:
                        Enrollment.objects.get_or_create(
                            student=target_user,
                            course=crs,
                            defaults={
                                'status': EnrollmentStatus.ACTIVE,
                                'source': EnrollmentSource.MANUAL,
                                'created_by': request.user
                            }
                        )

                removed_course_ids = enrolled_course_ids - selected_course_ids
                if removed_course_ids:
                    Enrollment.objects.filter(student=target_user, course_id__in=removed_course_ids).update(status=EnrollmentStatus.CANCELLED)

                AuditLog.objects.create(
                    actor=request.user,
                    actor_type='ADMIN',
                    academy=target_user.academy,
                    action=AuditAction.STUDENT_UPDATED,
                    category=AuditCategory.STUDENT,
                    target_type='User',
                    target_id=str(target_user.id),
                    description=f"Updated profile and course enrollments for student '{target_user.email}'."
                )

                messages.success(request, f"Updated student '{target_user.email}'.")
                return redirect('control_panel:student_detail', pk=pk)

    return render(request, 'control_panel/students/edit.html', {
        'active_nav': 'students',
        'target_user': target_user,
        'academies': academies,
        'academy_courses_map': academy_courses_map,
        'enrolled_course_ids': list(enrolled_course_ids),
        'errors': errors,
    })

@super_admin_required
def student_enable_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        target_user.is_active = True
        target_user.save()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='ADMIN',
            academy=target_user.academy,
            action=AuditAction.USER_ACTIVATED,
            category=AuditCategory.STUDENT,
            target_type='User',
            target_id=str(pk),
            description=f"Enabled student account '{target_user.email}'."
        )
        messages.success(request, f"Student '{target_user.email}' enabled.")
    return redirect('control_panel:students_list')

@super_admin_required
def student_disable_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        target_user.is_active = False
        target_user.save()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='ADMIN',
            academy=target_user.academy,
            action=AuditAction.USER_DEACTIVATED,
            category=AuditCategory.STUDENT,
            target_type='User',
            target_id=str(pk),
            description=f"Disabled student account '{target_user.email}'."
        )
        messages.warning(request, f"Student '{target_user.email}' disabled.")
    return redirect('control_panel:students_list')

@super_admin_required
def student_delete_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    enrollments_count = Enrollment.objects.filter(student=target_user).count()

    if request.method == 'POST':
        email = target_user.email
        target_user.delete()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='ADMIN',
            action=AuditAction.USER_DEACTIVATED,
            category=AuditCategory.STUDENT,
            target_type='User',
            target_id=str(pk),
            description=f"Deleted student account '{email}'."
        )
        messages.success(request, f"Student '{email}' deleted.")
        return redirect('control_panel:students_list')

    return render(request, 'control_panel/students/confirm_delete.html', {
        'active_nav': 'students',
        'target_user': target_user,
        'enrollments_count': enrollments_count,
    })

# --------------------------------------------------------------
# Courses Views
# --------------------------------------------------------------

@super_admin_required
def courses_list_view(request):
    q = request.GET.get('q', '').strip()
    academy_id = request.GET.get('academy', '').strip()
    category_id = request.GET.get('category', '').strip()
    status_filter = request.GET.get('status', '').strip()

    qs = Course.objects.select_related('academy', 'category').annotate(enrollments_count=Count('enrollments')).order_by('-created_at')

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
        if request.user.academy:
            qs = qs.filter(academy=request.user.academy)
        else:
            qs = qs.none()
    elif academy_id:
        qs = qs.filter(academy_id=academy_id)

    if category_id:
        qs = qs.filter(category_id=category_id)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(short_description__icontains=q) | Q(academy__name__icontains=q) | Q(category__name__icontains=q))

    total_courses = qs.count()
    published_courses = qs.filter(status=CourseStatus.PUBLISHED).count()
    draft_courses = qs.filter(status=CourseStatus.DRAFT).count()
    total_enrollments = Enrollment.objects.filter(course__in=qs).count()

    paginator = Paginator(qs, 20)
    courses_page = paginator.get_page(request.GET.get('page'))

    academies = Academy.objects.all().order_by('name')
    categories = CourseCategory.objects.all().order_by('name')

    context = {
        'active_nav': 'courses',
        'courses_page': courses_page,
        'academies': academies,
        'categories': categories,
        'q': q,
        'selected_academy': academy_id,
        'selected_category': category_id,
        'selected_status': status_filter,
        'total_courses': total_courses,
        'published_courses': published_courses,
        'draft_courses': draft_courses,
        'total_enrollments': total_enrollments,
        'statuses': CourseStatus.choices,
    }
    return render(request, 'control_panel/courses/index.html', context)

@super_admin_required
def course_create_view(request):
    errors = {}
    form_data = {}
    academies = Academy.objects.all().order_by('name')
    from courses.models import CourseCategory, CourseLevel, CourseStatus
    categories = CourseCategory.objects.all().order_by('name')

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF] and request.user.academy:
        academies = Academy.objects.filter(id=request.user.academy.id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        short_description = request.POST.get('short_description', '').strip()
        description = request.POST.get('description', '').strip()
        academy_id = request.POST.get('academy_id')
        category_id = request.POST.get('category_id')
        level = request.POST.get('level', CourseLevel.ALL_LEVELS)
        price_val = request.POST.get('price', '0.00').strip()
        is_free = request.POST.get('is_free') == 'true'
        status = request.POST.get('status', CourseStatus.DRAFT)

        form_data = {
            'title': title,
            'subtitle': subtitle,
            'short_description': short_description,
            'description': description,
            'academy_id': academy_id,
            'category_id': category_id,
            'level': level,
            'price': price_val,
            'is_free': is_free,
            'status': status,
        }

        if not title:
            errors['title'] = "Course Title is required."
        if not academy_id:
            errors['academy_id'] = "Academy selection is required."

        academy = Academy.objects.filter(pk=academy_id).first() if academy_id else None
        category = CourseCategory.objects.filter(pk=category_id).first() if category_id else None

        price = Decimal('0.00')
        if not is_free and price_val:
            try:
                price = Decimal(price_val)
            except Exception:
                errors['price'] = "Enter a valid course price."

        if not errors and academy:
            from django.db import transaction
            with transaction.atomic():
                course = Course.objects.create(
                    title=title,
                    subtitle=subtitle,
                    short_description=short_description,
                    description=description,
                    academy=academy,
                    category=category,
                    level=level,
                    price=price,
                    is_free=is_free,
                    status=status
                )

                AuditLog.objects.create(
                    actor=request.user,
                    actor_type='ADMIN',
                    academy=academy,
                    action=AuditAction.COURSE_CREATED,
                    category=AuditCategory.COURSE,
                    target_type='Course',
                    target_id=str(course.id),
                    description=f"Created course '{course.title}' in Academy '{academy.name}'."
                )

                messages.success(request, f"Course '{course.title}' created successfully.")
                return redirect('control_panel:course_detail', pk=course.id)

    return render(request, 'control_panel/courses/create.html', {
        'active_nav': 'courses',
        'academies': academies,
        'categories': categories,
        'levels': CourseLevel.choices,
        'statuses': CourseStatus.choices,
        'errors': errors,
        'form_data': form_data,
    })

@super_admin_required
def course_detail_view(request, pk):
    course = get_object_or_404(Course.objects.select_related('academy', 'category'), pk=pk)

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
        if request.user.academy and course.academy != request.user.academy:
            return HttpResponseForbidden("Access Denied.")

    from courses.models import CourseModule
    modules = CourseModule.objects.filter(course=course).order_by('order_index')
    enrollments = Enrollment.objects.filter(course=course).select_related('student')
    recent_logs = AuditLog.objects.filter(target_id=str(pk)).order_by('-occurred_at')[:10]

    context = {
        'active_nav': 'courses',
        'course': course,
        'modules': modules,
        'enrollments': enrollments,
        'enrollments_count': enrollments.count(),
        'modules_count': modules.count(),
        'recent_logs': recent_logs,
    }
    return render(request, 'control_panel/courses/detail.html', context)

@super_admin_required
def course_edit_view(request, pk):
    course = get_object_or_404(Course, pk=pk)

    if request.user.role_code in [SystemRoleCode.ACADEMY_ADMIN, SystemRoleCode.ACADEMY_STAFF]:
        if request.user.academy and course.academy != request.user.academy:
            return HttpResponseForbidden("Access Denied.")

    errors = {}
    academies = Academy.objects.all().order_by('name')
    from courses.models import CourseCategory, CourseLevel, CourseStatus
    categories = CourseCategory.objects.all().order_by('name')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        short_description = request.POST.get('short_description', '').strip()
        description = request.POST.get('description', '').strip()
        academy_id = request.POST.get('academy_id')
        category_id = request.POST.get('category_id')
        level = request.POST.get('level', course.level)
        price_val = request.POST.get('price', str(course.price)).strip()
        is_free = request.POST.get('is_free') == 'true'
        status = request.POST.get('status', course.status)

        if not title:
            errors['title'] = "Course Title cannot be empty."

        price = Decimal('0.00')
        if not is_free and price_val:
            try:
                price = Decimal(price_val)
            except Exception:
                errors['price'] = "Enter a valid course price."

        if not errors:
            course.title = title
            course.subtitle = subtitle
            course.short_description = short_description
            course.description = description
            if academy_id:
                course.academy = Academy.objects.filter(pk=academy_id).first()
            if category_id:
                course.category = CourseCategory.objects.filter(pk=category_id).first()
            course.level = level
            course.price = price
            course.is_free = is_free
            course.status = status
            course.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='ADMIN',
                academy=course.academy,
                action=AuditAction.COURSE_UPDATED,
                category=AuditCategory.COURSE,
                target_type='Course',
                target_id=str(course.id),
                description=f"Updated course details for '{course.title}'."
            )

            messages.success(request, f"Course '{course.title}' updated successfully.")
            return redirect('control_panel:course_detail', pk=pk)

    return render(request, 'control_panel/courses/edit.html', {
        'active_nav': 'courses',
        'course': course,
        'academies': academies,
        'categories': categories,
        'levels': CourseLevel.choices,
        'statuses': CourseStatus.choices,
        'errors': errors,
    })

@super_admin_required
def course_delete_view(request, pk):
    course = get_object_or_404(Course, pk=pk)
    enrollments_count = Enrollment.objects.filter(course=course).count()

    if request.method == 'POST':
        title = course.title
        from courses.models import CourseStatus
        course.status = CourseStatus.ARCHIVED
        course.is_active = False
        course.save()

        AuditLog.objects.create(
            actor=request.user,
            actor_type='ADMIN',
            academy=course.academy,
            action=AuditAction.COURSE_ARCHIVED,
            category=AuditCategory.COURSE,
            target_type='Course',
            target_id=str(pk),
            description=f"Archived/Deleted course '{title}'."
        )
        messages.success(request, f"Course '{title}' archived successfully.")
        return redirect('control_panel:courses_list')

    return render(request, 'control_panel/courses/confirm_delete.html', {
        'active_nav': 'courses',
        'course': course,
        'enrollments_count': enrollments_count,
    })

@super_admin_required
def course_enable_view(request, pk):
    course = get_object_or_404(Course, pk=pk)
    if request.method == 'POST':
        from courses.models import CourseStatus
        course.status = CourseStatus.PUBLISHED
        course.is_active = True
        course.save()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='ADMIN',
            academy=course.academy,
            action=AuditAction.COURSE_PUBLISHED,
            category=AuditCategory.COURSE,
            target_type='Course',
            target_id=str(pk),
            description=f"Published course '{course.title}'."
        )
        messages.success(request, f"Course '{course.title}' published successfully.")
    return redirect('control_panel:courses_list')

@super_admin_required
def course_disable_view(request, pk):
    course = get_object_or_404(Course, pk=pk)
    if request.method == 'POST':
        from courses.models import CourseStatus
        course.status = CourseStatus.DRAFT
        course.is_active = False
        course.save()
        messages.warning(request, f"Course '{course.title}' status changed to Draft.")
    return redirect('control_panel:courses_list')

# --------------------------------------------------------------
# Enrollments Views
# --------------------------------------------------------------

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

@super_admin_required
def enrollment_create_view(request):
    students = StudentProfile.objects.select_related('user').all()
    courses = Course.objects.select_related('academy').all()

    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        course_id = request.POST.get('course_id')
        student = get_object_or_404(StudentProfile, pk=student_id)
        course = get_object_or_404(Course, pk=course_id)

        enrollment = EnrollmentService.enroll_student(student=student, course=course)
        messages.success(request, f"Enrolled student '{student.user.full_name}' in course '{course.title}'.")
        return redirect('control_panel:enrollments_list')

    return render(request, 'control_panel/enrollments/create.html', {'students': students, 'courses': courses, 'active_nav': 'enrollments'})

@super_admin_required
def enrollment_cancel_view(request, pk):
    enrollment = get_object_or_404(Enrollment, pk=pk)
    if request.method == 'POST':
        enrollment.status = 'CANCELLED'
        enrollment.save()
        messages.warning(request, f"Cancelled enrollment for '{enrollment.student.user.full_name}'.")
    return redirect('control_panel:enrollments_list')





@super_admin_required
def features_redirect_view(request):
    """
    302 redirect from standalone /features/ to /pricing/
    """
    return redirect('control_panel:pricing_rules_list')

DEFAULT_PRICING_RULES = [
    {
        'code': 'STUDENT_BASE',
        'name': 'Student Base Price',
        'category': 'BASE PRICING',
        'icon': 'users',
        'billing_unit': 'PER_STUDENT',
        'credit_cost': 10,
        'description': 'Base credit rate charged per enrolled student.',
    },
    {
        'code': 'LESSONS',
        'name': 'Lessons',
        'category': 'FEATURE PRICING',
        'icon': 'book-open',
        'billing_unit': 'PER_STUDENT',
        'credit_cost': 2,
        'description': 'Video, audio, documents, questions, assessments, assignments, and learning resources.',
    },
    {
        'code': 'FEE_COLLECTION',
        'name': 'Fee Collection',
        'category': 'FEATURE PRICING',
        'icon': 'wallet',
        'billing_unit': 'PER_STUDENT',
        'credit_cost': 1,
        'description': 'Collect fees from students.',
    },
    {
        'code': 'COURSE_ANNOUNCEMENT',
        'name': 'Course Announcement',
        'category': 'FEATURE PRICING',
        'icon': 'bell',
        'billing_unit': 'PER_ANNOUNCEMENT',
        'credit_cost': 2,
        'description': 'Send announcements to course students.',
    },
    {
        'code': 'LIVE_CLASS',
        'name': 'Live Class',
        'category': 'FEATURE PRICING',
        'icon': 'video',
        'billing_unit': 'PER_STUDENT',
        'credit_cost': 2,
        'description': 'Run live classes for students.',
    },
    {
        'code': 'EMAIL_DELIVERY',
        'name': 'Email Delivery',
        'category': 'FEATURE PRICING',
        'icon': 'mail',
        'billing_unit': 'PER_EMAIL',
        'credit_cost': 1,
        'description': 'Send course-related emails.',
    },
    {
        'code': 'COMPLETION_CERTIFICATE',
        'name': 'Completion Certificate',
        'category': 'FEATURE PRICING',
        'icon': 'award',
        'billing_unit': 'PER_CERTIFICATE',
        'credit_cost': 3,
        'description': 'Issue course completion certificates.',
    },
    {
        'code': 'COURSE_DISCUSSION',
        'name': 'Course Discussion',
        'category': 'FEATURE PRICING',
        'icon': 'message-square',
        'billing_unit': 'PER_STUDENT',
        'credit_cost': 1,
        'description': 'Enable course discussions.',
    },
    {
        'code': 'ONE_TO_ONE_SESSION',
        'name': 'One-to-One Session',
        'category': 'FEATURE PRICING',
        'icon': 'user-check',
        'billing_unit': 'PER_STUDENT',
        'credit_cost': 2,
        'description': 'Enable private student sessions.',
    },
]

def ensure_default_pricing_rules_seeded():
    canonical_codes = set()
    for data in DEFAULT_PRICING_RULES:
        canonical_codes.add(data['code'])
        rule, created = PricingRule.objects.get_or_create(
            code=data['code'],
            defaults={
                'name': data['name'],
                'category': data['category'],
                'icon': data['icon'],
                'billing_unit': data['billing_unit'],
                'credit_cost': data['credit_cost'],
                'description': data['description'],
                'is_active': True,
            }
        )
        if not created and not rule.is_active:
            rule.is_active = True
            rule.save(update_fields=['is_active'])

    PricingRule.objects.exclude(code__in=canonical_codes).update(is_active=False)

# --------------------------------------------------------------
# Central Pricing Configuration Views
# --------------------------------------------------------------

@super_admin_required
def pricing_rules_list_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.view')):
        return render(request, 'control_panel/403.html', status=403)

    ensure_default_pricing_rules_seeded()

    can_edit = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.update'))
    can_create = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.create'))
    can_delete = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.delete'))

    if request.method == 'POST':
        if not can_edit:
            return render(request, 'control_panel/403.html', status=403)

        from django.db import transaction
        with transaction.atomic():
            updated_count = 0
            all_rules = PricingRule.objects.all()
            for rule in all_rules:
                prefix = f"rule_{rule.id}_"
                unit_key = prefix + "unit"
                cost_key = prefix + "cost"
                active_key = prefix + "active"

                if unit_key in request.POST or cost_key in request.POST or active_key in request.POST:
                    new_unit = request.POST.get(unit_key, rule.billing_unit).strip()
                    new_cost_str = request.POST.get(cost_key, str(rule.credit_cost)).strip()
                    is_act = request.POST.get(active_key) == 'true'

                    try:
                        new_cost = int(new_cost_str)
                        if new_cost < 0:
                            new_cost = 0
                    except ValueError:
                        new_cost = rule.credit_cost

                    rule.billing_unit = new_unit
                    rule.credit_cost = new_cost
                    rule.is_active = is_act
                    rule.save()
                    updated_count += 1

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.SYSTEM,
                target_type='PricingRule',
                target_id='bulk',
                description=f"Bulk updated credit costs for {updated_count} pricing rules."
            )

            messages.success(request, f"Pricing updated successfully. ({updated_count} rules saved)")
            return redirect('control_panel:pricing_rules_list')

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    canonical_codes = [
        'STUDENT_BASE',
        'LESSONS',
        'FEE_COLLECTION',
        'COURSE_ANNOUNCEMENT',
        'LIVE_CLASS',
        'EMAIL_DELIVERY',
        'COMPLETION_CERTIFICATE',
        'COURSE_DISCUSSION',
        'ONE_TO_ONE_SESSION'
    ]
    qs = PricingRule.objects.filter(code__in=canonical_codes)
    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q) | Q(billing_unit__icontains=q))

    pricing_rules = list(qs)
    total_rules = len(pricing_rules)
    active_rules = sum(1 for r in pricing_rules if r.is_active)
    billing_units_count = len(set(r.billing_unit for r in pricing_rules))

    context = {
        'active_nav': 'pricing',
        'pricing_rules': pricing_rules,
        'q': q,
        'status_filter': status_filter,
        'total_rules': total_rules,
        'active_rules': active_rules,
        'billing_units_count': billing_units_count,
        'can_create': can_create,
        'can_edit': can_edit,
        'can_delete': can_delete,
    }
    return render(request, 'control_panel/pricing/index.html', context)

@super_admin_required
def pricing_rule_create_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.create')):
        return render(request, 'control_panel/403.html', status=403)

    errors = {}
    form_data = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code_input = request.POST.get('code', '').strip().upper()
        description = request.POST.get('description', '').strip()
        billing_unit = request.POST.get('billing_unit', 'Per Email').strip()
        credit_cost_val = request.POST.get('credit_cost', '1').strip()
        is_active = request.POST.get('is_active') == 'true'

        code = code_input or slugify(name).upper().replace('-', '_')

        form_data = {
            'name': name,
            'code': code,
            'description': description,
            'billing_unit': billing_unit,
            'credit_cost': credit_cost_val,
            'is_active': is_active,
        }

        if not name:
            errors['name'] = "Pricing rule name is required."
        if not code:
            errors['code'] = "Pricing code is required."
        elif PricingRule.objects.filter(code=code).exists():
            errors['code'] = f"The pricing code '{code}' is already in use."

        try:
            credit_cost = int(credit_cost_val)
        except Exception:
            errors['credit_cost'] = "Enter a valid credit cost."
            credit_cost = 1

        if not errors:
            from django.db import transaction
            with transaction.atomic():
                rule = PricingRule.objects.create(
                    name=name,
                    code=code,
                    description=description,
                    billing_unit=billing_unit,
                    credit_cost=credit_cost,
                    is_active=is_active
                )

                AuditLog.objects.create(
                    actor=request.user,
                    actor_type='SUPER_ADMIN',
                    action=AuditAction.ACADEMY_CREATED,
                    category=AuditCategory.SYSTEM,
                    target_type='PricingRule',
                    target_id=str(rule.id),
                    description=f"Created pricing rule '{rule.name}' ({rule.code}) - {credit_cost} Credits per {billing_unit}."
                )

                messages.success(request, f"Pricing rule '{rule.name}' created successfully.")
                return redirect('control_panel:pricing_rule_detail', pk=rule.id)

    return render(request, 'control_panel/pricing/create.html', {
        'active_nav': 'pricing',
        'errors': errors,
        'form_data': form_data,
    })

@super_admin_required
def pricing_rule_detail_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.view')):
        return render(request, 'control_panel/403.html', status=403)

    rule = get_object_or_404(PricingRule, pk=pk)
    recent_logs = AuditLog.objects.filter(target_id=str(pk)).order_by('-occurred_at')[:10]

    can_edit = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.update'))
    can_delete = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.delete'))

    context = {
        'active_nav': 'pricing',
        'rule': rule,
        'recent_logs': recent_logs,
        'can_edit': can_edit,
        'can_delete': can_delete,
    }
    return render(request, 'control_panel/pricing/detail.html', context)

@super_admin_required
def pricing_rule_edit_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.update')):
        return render(request, 'control_panel/403.html', status=403)

    rule = get_object_or_404(PricingRule, pk=pk)
    errors = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        billing_unit = request.POST.get('billing_unit', rule.billing_unit).strip()
        credit_cost_val = request.POST.get('credit_cost', str(rule.credit_cost)).strip()
        is_active = request.POST.get('is_active') == 'true'

        if not name:
            errors['name'] = "Pricing rule name cannot be empty."

        try:
            credit_cost = int(credit_cost_val)
        except Exception:
            errors['credit_cost'] = "Enter a valid credit cost."
            credit_cost = rule.credit_cost

        if not errors:
            rule.name = name
            rule.description = description
            rule.billing_unit = billing_unit
            rule.credit_cost = credit_cost
            rule.is_active = is_active
            rule.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.SYSTEM,
                target_type='PricingRule',
                target_id=str(rule.id),
                description=f"Updated pricing rule '{rule.name}' ({rule.code})."
            )

            messages.success(request, f"Pricing rule '{rule.name}' updated successfully.")
            return redirect('control_panel:pricing_rule_detail', pk=pk)

    return render(request, 'control_panel/pricing/edit.html', {
        'active_nav': 'pricing',
        'rule': rule,
        'errors': errors,
    })

@super_admin_required
def pricing_rule_delete_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.delete')):
        return render(request, 'control_panel/403.html', status=403)

    rule = get_object_or_404(PricingRule, pk=pk)

    if request.method == 'POST':
        name = rule.name
        rule.delete()
        messages.success(request, f"Pricing rule '{name}' deleted successfully.")
        return redirect('control_panel:pricing_rules_list')

    return render(request, 'control_panel/pricing/confirm_delete.html', {
        'active_nav': 'pricing',
        'rule': rule,
    })

@super_admin_required
def pricing_rule_enable_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.update')):
        return render(request, 'control_panel/403.html', status=403)

    rule = get_object_or_404(PricingRule, pk=pk)
    if request.method == 'POST':
        rule.is_active = True
        rule.save()
        messages.success(request, f"Pricing rule '{rule.name}' enabled.")
    return redirect('control_panel:pricing_rules_list')

@super_admin_required
def pricing_rule_disable_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'pricing.update')):
        return render(request, 'control_panel/403.html', status=403)

    rule = get_object_or_404(PricingRule, pk=pk)
    if request.method == 'POST':
        rule.is_active = False
        rule.save()
        messages.warning(request, f"Pricing rule '{rule.name}' disabled.")
    return redirect('control_panel:pricing_rules_list')

@super_admin_required
def feature_create_view(request):
    errors = {}
    form_data = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code_input = request.POST.get('code', '').strip().upper()
        description = request.POST.get('description', '').strip()
        category = request.POST.get('category', 'GENERAL').strip().upper()
        is_active = request.POST.get('is_active') == 'true'
        enabled_globally = request.POST.get('enabled_globally') == 'true'
        is_billable = request.POST.get('is_billable') == 'true'

        code = code_input or slugify(name).upper().replace('-', '_')

        form_data = {
            'name': name,
            'code': code,
            'description': description,
            'category': category,
            'is_active': is_active,
            'enabled_globally': enabled_globally,
            'is_billable': is_billable,
        }

        if not name:
            errors['name'] = "Feature name is required."
        if not code:
            errors['code'] = "Feature code is required."
        elif FeatureDefinition.objects.filter(code=code).exists():
            errors['code'] = f"The feature code '{code}' already exists."

        if not errors:
            from django.db import transaction
            with transaction.atomic():
                feature = FeatureDefinition.objects.create(
                    name=name,
                    code=code,
                    description=description,
                    category=category,
                    is_active=is_active,
                    enabled_globally=enabled_globally,
                    is_billable=is_billable
                )

                AuditLog.objects.create(
                    actor=request.user,
                    actor_type='SUPER_ADMIN',
                    action=AuditAction.SYSTEM,
                    category=AuditCategory.SYSTEM,
                    target_type='FeatureDefinition',
                    target_id=str(feature.id),
                    description=f"Created platform feature definition '{feature.name}' ({feature.code})."
                )

                messages.success(request, f"Feature '{feature.name}' created successfully.")
                return redirect('control_panel:feature_detail', pk=feature.id)

    return render(request, 'control_panel/features/create.html', {
        'active_nav': 'features',
        'errors': errors,
        'form_data': form_data,
    })

@super_admin_required
def feature_detail_view(request, pk):
    feature = get_object_or_404(FeatureDefinition, pk=pk)
    recent_logs = AuditLog.objects.filter(target_id=str(pk)).order_by('-occurred_at')[:10]

    context = {
        'active_nav': 'features',
        'feature': feature,
        'recent_logs': recent_logs,
    }
    return render(request, 'control_panel/features/detail.html', context)

@super_admin_required
def feature_edit_view(request, pk):
    feature = get_object_or_404(FeatureDefinition, pk=pk)
    errors = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        category = request.POST.get('category', feature.category).strip().upper()
        is_active = request.POST.get('is_active') == 'true'
        enabled_globally = request.POST.get('enabled_globally') == 'true'
        is_billable = request.POST.get('is_billable') == 'true'

        if not name:
            errors['name'] = "Feature name cannot be empty."

        if not errors:
            feature.name = name
            feature.description = description
            feature.category = category
            feature.is_active = is_active
            feature.enabled_globally = enabled_globally
            feature.is_billable = is_billable
            feature.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.SYSTEM,
                category=AuditCategory.SYSTEM,
                target_type='FeatureDefinition',
                target_id=str(feature.id),
                description=f"Updated details for feature '{feature.name}'."
            )

            messages.success(request, f"Feature '{feature.name}' updated successfully.")
            return redirect('control_panel:feature_detail', pk=pk)

    return render(request, 'control_panel/features/edit.html', {
        'active_nav': 'features',
        'feature': feature,
        'errors': errors,
    })

@super_admin_required
def feature_delete_view(request, pk):
    feature = get_object_or_404(FeatureDefinition, pk=pk)

    if request.method == 'POST':
        name = feature.name
        feature.delete()
        messages.success(request, f"Feature '{name}' deleted successfully.")
        return redirect('control_panel:features_list')

    return render(request, 'control_panel/features/confirm_delete.html', {
        'active_nav': 'features',
        'feature': feature,
    })

@super_admin_required
def feature_enable_view(request, pk):
    feature = get_object_or_404(FeatureDefinition, pk=pk)
    if request.method == 'POST':
        feature.is_active = True
        feature.save()
        messages.success(request, f"Feature '{feature.name}' enabled successfully.")
    return redirect('control_panel:features_list')

@super_admin_required
def feature_disable_view(request, pk):
    feature = get_object_or_404(FeatureDefinition, pk=pk)
    if request.method == 'POST':
        feature.is_active = False
        feature.save()
        messages.warning(request, f"Feature '{feature.name}' disabled.")
    return redirect('control_panel:features_list')

@super_admin_required
def entitlements_list_view(request):
    entitlements = PlanFeature.objects.select_related('plan', 'feature').all()
    context = {
        'active_nav': 'features',
        'entitlements': entitlements,
    }
    return render(request, 'control_panel/plans/entitlements.html', context)

# --------------------------------------------------------------
# Pricing Engine & Credit Engine Views
# --------------------------------------------------------------

@super_admin_required
def pricing_engine_view(request):
    features = FeatureDefinition.objects.all()
    if request.method == 'POST':
        for feat in features:
            bp_key = f"base_price_{feat.id}"
            if bp_key in request.POST:
                feat.base_price = Decimal(request.POST.get(bp_key, '0.00'))
                feat.save()
        messages.success(request, "Pricing engine rates saved.")
        return redirect('control_panel:pricing_engine')

    context = {
        'active_nav': 'pricing',
        'features': features,
    }
    return render(request, 'control_panel/pricing/index.html', context)

@super_admin_required
def credits_overview_view(request):
    rates = CreditRate.objects.filter(is_active=True)
    packages = CreditPackage.objects.all()
    coupons = CreditPurchaseCoupon.objects.all()

    context = {
        'active_nav': 'credit_engine',
        'rates': rates,
        'packages': packages,
        'coupons': coupons,
    }
    return render(request, 'control_panel/credits/engine.html', context)

@super_admin_required
def credit_rates_list_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.view')):
        return render(request, 'control_panel/403.html', status=403)

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    qs = CreditRate.objects.all().order_by('feature_key')

    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(feature_key__icontains=q) | Q(description__icontains=q))

    total_rates = qs.count()
    active_rates = qs.filter(is_active=True).count()

    paginator = Paginator(qs, 20)
    rates_page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'credit_rates',
        'rates_page': rates_page,
        'q': q,
        'status_filter': status_filter,
        'total_rates': total_rates,
        'active_rates': active_rates,
    }
    return render(request, 'control_panel/credits/rates.html', context)

credit_rates_view = credit_rates_list_view

@super_admin_required
def credit_rate_create_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust')):
        return render(request, 'control_panel/403.html', status=403)

    errors = {}
    form_data = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        price_val = request.POST.get('price', '499.00').strip()
        credits_val = request.POST.get('credits', '500').strip()
        currency_raw = request.POST.get('currency', 'INR').strip()
        from core.utils import normalize_currency
        try:
            currency_val = normalize_currency(currency_raw)
        except Exception:
            errors['currency'] = "Currency must be a 3-letter code such as INR."
            currency_val = 'INR'
        is_purchasable_raw = request.POST.get('is_purchasable')
        is_purchasable = is_purchasable_raw == 'true' if is_purchasable_raw is not None else True
        is_active = request.POST.get('is_active') == 'true'

        # Auto-generate unique feature key from Package Name
        base_key = slugify(name).upper().replace('-', '_')
        if not base_key:
            base_key = "CREDIT_PACKAGE"
        feature_key = base_key
        counter = 1
        while CreditRate.objects.filter(feature_key=feature_key).exists():
            feature_key = f"{base_key}_{counter}"
            counter += 1

        form_data = {
            'name': name,
            'feature_key': feature_key,
            'description': description,
            'price': price_val,
            'credits': credits_val,
            'currency': currency_val,
            'is_purchasable': is_purchasable,
            'is_active': is_active,
        }

        if not name:
            errors['name'] = "Package Name is required."

        try:
            price = Decimal(price_val)
        except Exception:
            errors['price'] = "Enter a valid purchase price."
            price = Decimal('0.00')

        try:
            credits_num = Decimal(credits_val)
        except Exception:
            errors['credits'] = "Enter a valid credit quantity."
            credits_num = Decimal('0.000000')

        # Canonical backend defaults for internal model schema compatibility
        billing_type = 'FIXED'
        unit_size = Decimal('1.0000')
        credit_cost = credits_num if credits_num > 0 else Decimal('1.0000')

        if not errors:
            rate = CreditRate.objects.create(
                name=name,
                feature_key=feature_key,
                description=description,
                billing_type=billing_type,
                unit_size=unit_size,
                credit_cost=credit_cost,
                price=price,
                credits=credits_num,
                currency=currency_val,
                is_purchasable=is_purchasable,
                is_active=is_active
            )

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.ACADEMY_CREATED,
                category=AuditCategory.SYSTEM,
                target_type='CreditRate',
                target_id=str(rate.id),
                description=f"Created Credit Package '{rate.name}' ({rate.feature_key}) for ₹{price} ({credits_num} credits)."
            )

            messages.success(request, f"Credit Package '{rate.name}' created successfully.")
            return redirect('control_panel:credit_rates')

    return render(request, 'control_panel/credits/rate_form.html', {
        'active_nav': 'credit_rates',
        'is_edit': False,
        'errors': errors,
        'form_data': form_data,
        'billing_types': [('PER_UNIT', 'Per Unit'), ('PER_BLOCK', 'Per Block'), ('FIXED', 'Fixed Rate')],
    })

@super_admin_required
def credit_rate_detail_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.view')):
        return render(request, 'control_panel/403.html', status=403)

    rate = get_object_or_404(CreditRate, pk=pk)
    recent_logs = AuditLog.objects.filter(target_id=str(pk)).order_by('-occurred_at')[:10]

    context = {
        'active_nav': 'credit_rates',
        'rate': rate,
        'recent_logs': recent_logs,
    }
    return render(request, 'control_panel/credits/rate_detail.html', context)

@super_admin_required
def credit_rate_edit_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust')):
        return render(request, 'control_panel/403.html', status=403)

    rate = get_object_or_404(CreditRate, pk=pk)
    errors = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        price_val = request.POST.get('price', str(rate.price)).strip()
        credits_val = request.POST.get('credits', str(rate.credits)).strip()
        currency_raw = request.POST.get('currency', rate.currency).strip()
        from core.utils import normalize_currency
        try:
            currency_val = normalize_currency(currency_raw)
        except Exception:
            errors['currency'] = "Currency must be a 3-letter code such as INR."
            currency_val = 'INR'
        is_purchasable = request.POST.get('is_purchasable') == 'true'
        is_active = request.POST.get('is_active') == 'true'

        if not name:
            errors['name'] = "Package Name cannot be empty."

        try:
            price = Decimal(price_val)
        except Exception:
            errors['price'] = "Enter a valid purchase price."
            price = rate.price

        try:
            credits_num = Decimal(credits_val)
        except Exception:
            errors['credits'] = "Enter a valid credit quantity."
            credits_num = rate.credits

        if not errors:
            rate.name = name
            rate.description = description
            rate.price = price
            rate.credits = credits_num
            rate.credit_cost = credits_num if credits_num > 0 else Decimal('1.0000')
            rate.currency = currency_val
            rate.is_purchasable = is_purchasable
            rate.is_active = is_active
            rate.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.SYSTEM,
                target_type='CreditRate',
                target_id=str(rate.id),
                description=f"Updated Credit Package '{rate.name}' ({rate.feature_key}) to ₹{price} ({credits_num} credits)."
            )

            messages.success(request, f"Credit Package '{rate.name}' updated successfully.")
            return redirect('control_panel:credit_rates')

    return render(request, 'control_panel/credits/rate_form.html', {
        'active_nav': 'credit_rates',
        'is_edit': True,
        'rate': rate,
        'errors': errors,
        'billing_types': [('PER_UNIT', 'Per Unit'), ('PER_BLOCK', 'Per Block'), ('FIXED', 'Fixed Rate')],
    })

@super_admin_required
def credit_rate_delete_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust')):
        return render(request, 'control_panel/403.html', status=403)

    rate = get_object_or_404(CreditRate, pk=pk)
    if request.method == 'POST':
        name = rate.name
        try:
            rate.delete()
            messages.success(request, f"Package '{name}' deleted successfully.")
        except ProtectedError:
            rate.is_active = False
            rate.is_purchasable = False
            rate.save()
            messages.warning(request, f"Package '{name}' has existing purchase history and cannot be permanently deleted. It has been disabled instead.")
        except Exception:
            rate.is_active = False
            rate.is_purchasable = False
            rate.save()
            messages.warning(request, f"Package '{name}' has associated records. It has been disabled and removed from purchase options.")
        return redirect('control_panel:credit_rates')

    return redirect('control_panel:credit_rates')

@super_admin_required
def credit_rate_enable_view(request, pk):
    rate = get_object_or_404(CreditRate, pk=pk)
    if request.method == 'POST':
        rate.is_active = True
        rate.save()
        messages.success(request, f"Credit rate '{rate.name}' enabled successfully.")
    return redirect('control_panel:credit_rates')

@super_admin_required
def credit_rate_disable_view(request, pk):
    rate = get_object_or_404(CreditRate, pk=pk)
    if request.method == 'POST':
        rate.is_active = False
        rate.save()
        messages.warning(request, f"Credit rate '{rate.name}' disabled.")
    return redirect('control_panel:credit_rates')

@super_admin_required
def credit_coupons_list_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.view')):
        return render(request, 'control_panel/403.html', status=403)

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    qs = CreditPurchaseCoupon.objects.all().order_by('-created_at')

    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(description__icontains=q))

    total_coupons = qs.count()
    active_coupons = qs.filter(is_active=True).count()

    paginator = Paginator(qs, 20)
    coupons_page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'credit_coupons',
        'coupons_page': coupons_page,
        'q': q,
        'status_filter': status_filter,
        'total_coupons': total_coupons,
        'active_coupons': active_coupons,
    }
    return render(request, 'control_panel/credits/coupons.html', context)

credit_coupons_view = credit_coupons_list_view

@super_admin_required
def credit_coupon_create_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust')):
        return render(request, 'control_panel/403.html', status=403)

    errors = {}
    form_data = {}

    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        description = request.POST.get('description', '').strip()
        discount_type = request.POST.get('discount_type', 'PERCENTAGE').strip().upper()
        discount_value_val = request.POST.get('discount_value', '0.00').strip()
        min_purchase_val = request.POST.get('min_purchase_amount', '0.00').strip()
        usage_limit_val = request.POST.get('usage_limit', '').strip()
        is_active = request.POST.get('is_active') == 'true'

        form_data = {
            'code': code,
            'description': description,
            'discount_type': discount_type,
            'discount_value': discount_value_val,
            'min_purchase_amount': min_purchase_val,
            'usage_limit': usage_limit_val,
            'is_active': is_active,
        }

        if not code:
            errors['code'] = "Coupon code is required."
        elif CreditPurchaseCoupon.objects.filter(code=code).exists():
            errors['code'] = f"The coupon code '{code}' already exists."

        try:
            discount_value = Decimal(discount_value_val)
        except Exception:
            errors['discount_value'] = "Enter a valid discount value."
            discount_value = Decimal('0.00')

        try:
            min_purchase_amount = Decimal(min_purchase_val)
        except Exception:
            errors['min_purchase_amount'] = "Enter a valid minimum purchase amount."
            min_purchase_amount = Decimal('0.00')

        usage_limit = None
        if usage_limit_val:
            try:
                usage_limit = int(usage_limit_val)
            except Exception:
                errors['usage_limit'] = "Enter a valid integer usage limit."

        if not errors:
            coupon = CreditPurchaseCoupon.objects.create(
                code=code,
                description=description,
                discount_type=discount_type,
                discount_value=discount_value,
                min_purchase_amount=min_purchase_amount,
                usage_limit=usage_limit,
                is_active=is_active
            )

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.ACADEMY_CREATED,
                category=AuditCategory.SYSTEM,
                target_type='CreditPurchaseCoupon',
                target_id=str(coupon.id),
                description=f"Created credit coupon '{coupon.code}' ({discount_value} {discount_type})."
            )

            messages.success(request, f"Credit coupon '{coupon.code}' created successfully.")
            return redirect('control_panel:credit_coupon_detail', pk=coupon.id)

    return render(request, 'control_panel/credits/coupon_form.html', {
        'active_nav': 'credit_engine',
        'is_edit': False,
        'errors': errors,
        'form_data': form_data,
        'discount_types': [('PERCENTAGE', 'Percentage Discount'), ('FIXED_AMOUNT', 'Fixed Currency Amount'), ('BONUS_CREDITS', 'Bonus Credits')],
    })

@super_admin_required
def credit_coupon_detail_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.view')):
        return render(request, 'control_panel/403.html', status=403)

    coupon = get_object_or_404(CreditPurchaseCoupon, pk=pk)
    recent_logs = AuditLog.objects.filter(target_id=str(pk)).order_by('-occurred_at')[:10]

    context = {
        'active_nav': 'credit_engine',
        'coupon': coupon,
        'recent_logs': recent_logs,
    }
    return render(request, 'control_panel/credits/coupon_detail.html', context)

@super_admin_required
def credit_coupon_edit_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust')):
        return render(request, 'control_panel/403.html', status=403)

    coupon = get_object_or_404(CreditPurchaseCoupon, pk=pk)
    errors = {}

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        discount_type = request.POST.get('discount_type', coupon.discount_type).strip().upper()
        discount_value_val = request.POST.get('discount_value', str(coupon.discount_value)).strip()
        min_purchase_val = request.POST.get('min_purchase_amount', str(coupon.min_purchase_amount)).strip()
        usage_limit_val = request.POST.get('usage_limit', str(coupon.usage_limit or '')).strip()
        is_active = request.POST.get('is_active') == 'true'

        try:
            discount_value = Decimal(discount_value_val)
        except Exception:
            errors['discount_value'] = "Enter a valid discount value."
            discount_value = coupon.discount_value

        try:
            min_purchase_amount = Decimal(min_purchase_val)
        except Exception:
            errors['min_purchase_amount'] = "Enter a valid minimum purchase amount."
            min_purchase_amount = coupon.min_purchase_amount

        usage_limit = None
        if usage_limit_val:
            try:
                usage_limit = int(usage_limit_val)
            except Exception:
                errors['usage_limit'] = "Enter a valid integer usage limit."
                usage_limit = coupon.usage_limit

        if not errors:
            coupon.description = description
            coupon.discount_type = discount_type
            coupon.discount_value = discount_value
            coupon.min_purchase_amount = min_purchase_amount
            coupon.usage_limit = usage_limit
            coupon.is_active = is_active
            coupon.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.SYSTEM,
                target_type='CreditPurchaseCoupon',
                target_id=str(coupon.id),
                description=f"Updated credit coupon '{coupon.code}'."
            )

            messages.success(request, f"Credit coupon '{coupon.code}' updated successfully.")
            return redirect('control_panel:credit_coupon_detail', pk=pk)

    return render(request, 'control_panel/credits/coupon_form.html', {
        'active_nav': 'credit_engine',
        'is_edit': True,
        'coupon': coupon,
        'errors': errors,
        'discount_types': [('PERCENTAGE', 'Percentage Discount'), ('FIXED_AMOUNT', 'Fixed Currency Amount'), ('BONUS_CREDITS', 'Bonus Credits')],
    })

@super_admin_required
def credit_coupon_delete_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust')):
        return render(request, 'control_panel/403.html', status=403)

    coupon = get_object_or_404(CreditPurchaseCoupon, pk=pk)
    if request.method == 'POST':
        code = coupon.code
        coupon.delete()
        messages.success(request, f"Credit coupon '{code}' deleted successfully.")
        return redirect('control_panel:credit_coupons')

    return redirect('control_panel:credit_coupon_detail', pk=pk)

@super_admin_required
def credit_coupon_enable_view(request, pk):
    coupon = get_object_or_404(CreditPurchaseCoupon, pk=pk)
    if request.method == 'POST':
        coupon.is_active = True
        coupon.save()
        messages.success(request, f"Credit coupon '{coupon.code}' enabled successfully.")
    return redirect('control_panel:credit_coupons')

@super_admin_required
def credit_coupon_disable_view(request, pk):
    coupon = get_object_or_404(CreditPurchaseCoupon, pk=pk)
    if request.method == 'POST':
        coupon.is_active = False
        coupon.save()
        messages.warning(request, f"Credit coupon '{coupon.code}' disabled.")
    return redirect('control_panel:credit_coupons')



# --------------------------------------------------------------
# Wallets & Credit Ledger Views
# --------------------------------------------------------------

def ensure_academy_credit_wallets_exist():
    for academy in Academy.objects.all():
        CreditAccount.objects.get_or_create(
            academy=academy,
            defaults={'balance': Decimal('0.000000'), 'status': CreditAccountStatus.ACTIVE}
        )

# --------------------------------------------------------------
# Wallets & Credit Ledger Views
# --------------------------------------------------------------

@super_admin_required
def wallets_list_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.view')):
        return render(request, 'control_panel/403.html', status=403)

    ensure_academy_credit_wallets_exist()

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    qs = CreditAccount.objects.select_related('academy').all().order_by('-balance')

    if q:
        qs = qs.filter(
            Q(academy__name__icontains=q) |
            Q(academy__email__icontains=q) |
            Q(academy__slug__icontains=q)
        )

    if status_filter == 'positive':
        qs = qs.filter(balance__gt=0)
    elif status_filter == 'zero':
        qs = qs.filter(balance=0)
    elif status_filter == 'low':
        qs = qs.filter(balance__gt=0, balance__lte=100)

    total_academy_credits = CreditAccount.objects.aggregate(total=Sum('balance'))['total'] or Decimal('0')
    credits_added = CreditAccount.objects.aggregate(total=Sum('total_credited'))['total'] or Decimal('0')
    credits_used = CreditAccount.objects.aggregate(total=Sum('total_debited'))['total'] or Decimal('0')
    active_wallets_count = CreditAccount.objects.filter(status=CreditAccountStatus.ACTIVE).count()

    paginator = Paginator(qs, 20)
    accounts_page = paginator.get_page(request.GET.get('page'))

    can_adjust = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust') or has_permission(request.user, 'credits.add') or has_permission(request.user, 'credits.deduct'))

    context = {
        'active_nav': 'credits',
        'accounts_page': accounts_page,
        'q': q,
        'status_filter': status_filter,
        'total_academy_credits': int(total_academy_credits),
        'credits_added': int(credits_added),
        'credits_used': int(credits_used),
        'active_wallets_count': active_wallets_count,
        'can_adjust': can_adjust,
    }
    return render(request, 'control_panel/credits/wallets.html', context)

@super_admin_required
def wallet_detail_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.view')):
        return render(request, 'control_panel/403.html', status=403)

    try:
        account = CreditAccount.objects.select_related('academy').get(pk=pk)
    except (CreditAccount.DoesNotExist, ValueError):
        academy = get_object_or_404(Academy, pk=pk)
        account, _ = CreditAccount.objects.get_or_create(academy=academy)

    type_filter = request.GET.get('type', '').strip()
    entries_qs = CreditLedgerEntry.objects.filter(account=account).order_by('-occurred_at')

    if type_filter == 'credit':
        entries_qs = entries_qs.filter(entry_type=LedgerEntryType.CREDIT)
    elif type_filter == 'debit':
        entries_qs = entries_qs.filter(entry_type=LedgerEntryType.DEBIT)
    elif type_filter == 'purchase':
        entries_qs = entries_qs.filter(source_type=CreditSourceType.PURCHASE)
    elif type_filter == 'adjustment':
        entries_qs = entries_qs.filter(source_type=CreditSourceType.MANUAL_ADJUSTMENT)

    paginator = Paginator(entries_qs, 20)
    entries_page = paginator.get_page(request.GET.get('page'))

    can_adjust = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust') or has_permission(request.user, 'credits.add') or has_permission(request.user, 'credits.deduct'))

    context = {
        'active_nav': 'credits',
        'account': account,
        'entries_page': entries_page,
        'type_filter': type_filter,
        'can_adjust': can_adjust,
    }
    return render(request, 'control_panel/credits/wallet_detail.html', context)

@super_admin_required
def wallet_adjust_view(request, pk=None):
    can_adjust = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.adjust') or has_permission(request.user, 'credits.add') or has_permission(request.user, 'credits.deduct'))
    if not can_adjust:
        return render(request, 'control_panel/403.html', status=403)

    if request.method == 'POST':
        account_id = pk or request.POST.get('account_id')
        try:
            account = CreditAccount.objects.select_related('academy').get(pk=account_id)
        except (CreditAccount.DoesNotExist, ValueError):
            academy = get_object_or_404(Academy, pk=account_id)
            account, _ = CreditAccount.objects.get_or_create(academy=academy)

        action = request.POST.get('action', 'ADD').upper()
        amount_str = request.POST.get('amount', '0').strip()
        reason = request.POST.get('reason', '').strip()

        if not reason:
            messages.error(request, "Adjustment reason is mandatory.")
            return redirect('control_panel:wallet_detail', pk=account.pk)

        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                raise ValueError("Amount must be greater than zero.")
        except Exception:
            messages.error(request, "Enter a valid positive credit amount.")
            return redirect('control_panel:wallet_detail', pk=account.pk)

        from django.db import transaction
        with transaction.atomic():
            if action == 'DEDUCT':
                if account.balance < amount:
                    messages.error(request, f"Insufficient credit balance. Available: {int(account.balance)} Credits.")
                    return redirect('control_panel:wallet_detail', pk=account.pk)

                CreditsService.debit(
                    academy=account.academy,
                    amount=amount,
                    source_type=CreditSourceType.MANUAL_ADJUSTMENT,
                    description=reason,
                    created_by=request.user
                )
                messages.warning(request, f"Deducted {int(amount)} credits from {account.academy.name}.")
            else:
                CreditsService.credit(
                    academy=account.academy,
                    amount=amount,
                    source_type=CreditSourceType.MANUAL_ADJUSTMENT,
                    description=reason,
                    created_by=request.user
                )
                messages.success(request, f"Added {int(amount)} credits to {account.academy.name}.")

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                academy=account.academy,
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.SYSTEM,
                target_type='CreditAccount',
                target_id=str(account.id),
                description=f"Manual credit adjustment ({action} {int(amount)} credits): {reason}"
            )

        return redirect('control_panel:wallet_detail', pk=account.pk)

    return redirect('control_panel:credits_list')

@super_admin_required
def credit_transactions_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'credits.view')):
        return render(request, 'control_panel/403.html', status=403)

    entries = CreditLedgerEntry.objects.select_related('account__academy').order_by('-occurred_at')[:50]
    return render(request, 'control_panel/credits/transactions.html', {'entries': entries, 'active_nav': 'credits'})

# --------------------------------------------------------------
# Storage & Metering Views
# --------------------------------------------------------------

def format_bytes(bytes_val):
    if not bytes_val or bytes_val <= 0:
        return "0 B"
    b = float(bytes_val)
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while b >= 1024 and i < len(units) - 1:
        b /= 1024
        i += 1
    if i == 0:
        return f"{int(b)} B"
    return f"{b:.2f} {units[i]}"



@super_admin_required
def storage_control_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'storage.view')):
        return render(request, 'control_panel/403.html', status=403)

    q = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'storage_desc').strip()

    academies = Academy.objects.all()
    if q:
        academies = academies.filter(
            Q(name__icontains=q) |
            Q(email__icontains=q) |
            Q(slug__icontains=q)
        )

    academy_storage_list = []
    total_system_bytes = 0
    total_system_files = 0
    academies_using_storage = 0
    highest_consumer_name = "-"
    highest_consumer_bytes = 0

    for ac in academies:
        files_qs = MediaFile.objects.filter(academy_uuid=ac.id)
        agg = files_qs.aggregate(
            total_bytes=Sum('size_bytes'),
            file_count=Count('id')
        )
        bytes_used = agg['total_bytes'] or 0
        file_count = agg['file_count'] or 0

        images_count = files_qs.filter(Q(media_type='IMAGE') | Q(file_type='IMAGE')).count()
        videos_count = files_qs.filter(Q(media_type='VIDEO') | Q(file_type='VIDEO')).count()
        docs_count = files_qs.filter(Q(media_type='DOCUMENT') | Q(file_type='DOCUMENT')).count()
        last_file = files_qs.order_by('-created_at').first()
        last_upload_at = last_file.created_at if last_file else None

        if bytes_used > 0:
            academies_using_storage += 1

        if bytes_used > highest_consumer_bytes:
            highest_consumer_bytes = bytes_used
            highest_consumer_name = ac.name

        total_system_bytes += bytes_used
        total_system_files += file_count

        academy_storage_list.append({
            'academy': ac,
            'bytes_used': bytes_used,
            'formatted_bytes': format_bytes(bytes_used),
            'file_count': file_count,
            'images_count': images_count,
            'videos_count': videos_count,
            'docs_count': docs_count,
            'last_upload_at': last_upload_at,
        })

    # Sorting
    if sort_by == 'storage_asc':
        academy_storage_list.sort(key=lambda x: x['bytes_used'])
    elif sort_by == 'files_desc':
        academy_storage_list.sort(key=lambda x: x['file_count'], reverse=True)
    elif sort_by == 'name_asc':
        academy_storage_list.sort(key=lambda x: x['academy'].name.lower())
    else:  # storage_desc
        academy_storage_list.sort(key=lambda x: x['bytes_used'], reverse=True)

    paginator = Paginator(academy_storage_list, 20)
    storage_page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'storage',
        'storage_page': storage_page,
        'q': q,
        'sort_by': sort_by,
        'total_system_storage_formatted': format_bytes(total_system_bytes),
        'total_system_files': total_system_files,
        'academies_using_storage': academies_using_storage,
        'highest_consumer_name': highest_consumer_name,
        'highest_consumer_formatted': format_bytes(highest_consumer_bytes),
    }
    return render(request, 'control_panel/storage/index.html', context)

@super_admin_required
def academy_storage_detail_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'storage.view')):
        return render(request, 'control_panel/403.html', status=403)

    academy = get_object_or_404(Academy, pk=pk)
    files_qs = MediaFile.objects.filter(academy_uuid=academy.id).order_by('-created_at')

    total_bytes = files_qs.aggregate(total=Sum('size_bytes'))['total'] or 0
    total_files = files_qs.count()

    video_files = files_qs.filter(Q(media_type='VIDEO') | Q(file_type='VIDEO'))
    image_files = files_qs.filter(Q(media_type='IMAGE') | Q(file_type='IMAGE'))
    doc_files = files_qs.filter(Q(media_type='DOCUMENT') | Q(file_type='DOCUMENT'))
    audio_files = files_qs.filter(Q(media_type='AUDIO') | Q(file_type='AUDIO'))

    video_bytes = video_files.aggregate(total=Sum('size_bytes'))['total'] or 0
    image_bytes = image_files.aggregate(total=Sum('size_bytes'))['total'] or 0
    doc_bytes = doc_files.aggregate(total=Sum('size_bytes'))['total'] or 0
    audio_bytes = audio_files.aggregate(total=Sum('size_bytes'))['total'] or 0

    known_pks = list(video_files.values_list('pk', flat=True)) + \
                list(image_files.values_list('pk', flat=True)) + \
                list(doc_files.values_list('pk', flat=True)) + \
                list(audio_files.values_list('pk', flat=True))
    other_files = files_qs.exclude(pk__in=known_pks)
    other_bytes = other_files.aggregate(total=Sum('size_bytes'))['total'] or 0

    paginator = Paginator(files_qs, 20)
    files_page = paginator.get_page(request.GET.get('page'))

    recent_uploads = []
    for f in files_page:
        recent_uploads.append({
            'file': f,
            'formatted_size': format_bytes(f.size_bytes),
        })

    context = {
        'active_nav': 'storage',
        'academy': academy,
        'total_bytes_formatted': format_bytes(total_bytes),
        'total_files': total_files,
        'video_bytes_formatted': format_bytes(video_bytes),
        'image_bytes_formatted': format_bytes(image_bytes),
        'doc_bytes_formatted': format_bytes(doc_bytes),
        'audio_bytes_formatted': format_bytes(audio_bytes),
        'other_bytes_formatted': format_bytes(other_bytes),
        'video_count': video_files.count(),
        'image_count': image_files.count(),
        'doc_count': doc_files.count(),
        'audio_count': audio_files.count(),
        'other_count': other_files.count(),
        'files_page': files_page,
        'recent_uploads': recent_uploads,
    }
    return render(request, 'control_panel/storage/detail.html', context)

@super_admin_required
def storage_config_view(request):
    storage_config = StorageBillingConfig.objects.first() or StorageBillingConfig.objects.create()
    if request.method == 'POST':
        storage_config.price_per_unit = Decimal(request.POST.get('price_per_unit', '0.50'))
        storage_config.save()
        messages.success(request, "Storage config updated.")
    return redirect('control_panel:storage_control')

@super_admin_required
def usage_redirect_view(request):
    return redirect('control_panel:storage_control')

@super_admin_required
def payments_list_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'payments.view')):
        return render(request, 'control_panel/403.html', status=403)

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    sort_by = request.GET.get('sort', 'newest').strip()

    qs = PaymentOrder.objects.select_related('academy', 'payer', 'plan', 'coupon').all()

    if q:
        qs = qs.filter(
            Q(order_number__icontains=q) |
            Q(academy__name__icontains=q) |
            Q(academy__email__icontains=q) |
            Q(gateway_order_id__icontains=q) |
            Q(product_name_snapshot__icontains=q)
        )

    if status_filter:
        qs = qs.filter(status=status_filter)

    # Sorting
    if sort_by == 'oldest':
        qs = qs.order_by('created_at')
    elif sort_by == 'amount_desc':
        qs = qs.order_by('-final_amount')
    elif sort_by == 'amount_asc':
        qs = qs.order_by('final_amount')
    else:  # newest
        qs = qs.order_by('-created_at')

    # Summary metrics
    total_payments = PaymentOrder.objects.count()
    successful_payments = PaymentOrder.objects.filter(status__in=['COMPLETED', 'SUCCESSFUL', 'PAID']).count()
    pending_payments = PaymentOrder.objects.filter(status__in=['PENDING', 'CREATED', 'PROCESSING']).count()
    failed_payments = PaymentOrder.objects.filter(status__in=['FAILED', 'CANCELLED', 'EXPIRED']).count()

    total_revenue_val = PaymentOrder.objects.filter(status__in=['COMPLETED', 'SUCCESSFUL', 'PAID']).aggregate(total=Sum('final_amount'))['total'] or Decimal('0')

    paginator = Paginator(qs, 20)
    orders_page = paginator.get_page(request.GET.get('page'))

    can_refund = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'payments.refund'))

    context = {
        'active_nav': 'payments',
        'orders_page': orders_page,
        'q': q,
        'status_filter': status_filter,
        'sort_by': sort_by,
        'total_payments': total_payments,
        'successful_payments': successful_payments,
        'pending_payments': pending_payments,
        'failed_payments': failed_payments,
        'total_revenue': total_revenue_val,
        'can_refund': can_refund,
    }
    return render(request, 'control_panel/payments/index.html', context)

@super_admin_required
def payment_detail_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'payments.view')):
        return render(request, 'control_panel/403.html', status=403)

    order = get_object_or_404(PaymentOrder.objects.select_related('academy', 'payer', 'plan', 'coupon'), pk=pk)
    transactions = PaymentTransaction.objects.filter(order=order).order_by('-initiated_at')
    refunds = PaymentRefund.objects.filter(order=order).order_by('-requested_at')

    credit_entry = None
    if order.academy:
        credit_entry = CreditLedgerEntry.objects.filter(
            account__academy=order.academy,
            reference_id=str(order.order_number)
        ).first() or CreditLedgerEntry.objects.filter(
            account__academy=order.academy,
            reference_id=str(order.id)
        ).first()

    can_refund = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'payments.refund'))

    context = {
        'active_nav': 'payments',
        'order': order,
        'transactions': transactions,
        'refunds': refunds,
        'credit_entry': credit_entry,
        'can_refund': can_refund,
    }
    return render(request, 'control_panel/payments/detail.html', context)

@super_admin_required
def payment_refund_view(request, pk):
    can_refund = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'payments.refund'))
    if not can_refund:
        return render(request, 'control_panel/403.html', status=403)

    order = get_object_or_404(PaymentOrder, pk=pk)
    if request.method == 'POST':
        reason = request.POST.get('reason', 'Super Admin initiated refund').strip()

        from django.db import transaction
        with transaction.atomic():
            order.status = OrderStatus.REFUNDED
            order.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                academy=order.academy,
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.SYSTEM,
                target_type='PaymentOrder',
                target_id=str(order.id),
                description=f"Refunded payment order '{order.order_number}' (₹{order.final_amount}): {reason}"
            )

            messages.success(request, f"Payment #{order.order_number} marked as Refunded successfully.")

    return redirect('control_panel:payment_detail', pk=pk)

@super_admin_required
def transactions_list_view(request):
    transactions = PaymentTransaction.objects.select_related('order').order_by('-initiated_at')[:30]
    return render(request, 'control_panel/payments/transactions.html', {'transactions': transactions, 'active_nav': 'payments'})

@super_admin_required
def invoices_list_view(request):
    invoices = PaymentInvoice.objects.select_related('order').order_by('-issued_at')[:30]
    return render(request, 'control_panel/payments/invoices.html', {'invoices': invoices, 'active_nav': 'payments'})

# --------------------------------------------------------------
# Fees Collection Views
# --------------------------------------------------------------

@super_admin_required
def fees_list_view(request):
    accounts = StudentFeeAccount.objects.select_related('academy', 'course', 'student').order_by('-created_at')[:30]
    return render(request, 'control_panel/fees/index.html', {'accounts': accounts, 'active_nav': 'fees'})

@super_admin_required
def fee_detail_view(request, pk):
    account = get_object_or_404(StudentFeeAccount.objects.select_related('academy', 'course', 'student'), pk=pk)
    installments = FeeInstallment.objects.filter(fee_account=account)
    payments = FeePayment.objects.filter(fee_account=account)
    return render(request, 'control_panel/fees/detail.html', {'account': account, 'installments': installments, 'payments': payments, 'active_nav': 'fees'})

@super_admin_required
def fee_pay_view(request, pk):
    account = get_object_or_404(StudentFeeAccount, pk=pk)
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', '0.00'))
        method = request.POST.get('method', 'CASH')
        FeeCollectionService.record_fee_payment(account=account, amount=amount, payment_method=method, collected_by=request.user)
        messages.success(request, f"Recorded fee payment of ₹{amount} for {account.student.full_name}.")
    return redirect('control_panel:fee_detail', pk=pk)

# --------------------------------------------------------------
# Enrollments Views
# --------------------------------------------------------------

@super_admin_required
def enrollments_list_view(request):
    q = request.GET.get('q', '').strip()
    qs = Enrollment.objects.select_related('student', 'course__academy').order_by('-enrolled_at')

    if q:
        qs = qs.filter(Q(student__full_name__icontains=q) | Q(student__email__icontains=q) | Q(course__title__icontains=q))

    paginator = Paginator(qs, 20)
    enrollments = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'enrollments',
        'enrollments': enrollments,
        'q': q,
    }
    return render(request, 'control_panel/enrollments/index.html', context)

@super_admin_required
def enrollment_create_view(request):
    students = StudentProfile.objects.select_related('user').all()
    courses = Course.objects.select_related('academy').all()

    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        course_id = request.POST.get('course_id')
        student = get_object_or_404(StudentProfile, pk=student_id)
        course = get_object_or_404(Course, pk=course_id)

        enrollment = EnrollmentService.enroll_student(student=student, course=course)
        messages.success(request, f"Enrolled student '{student.user.full_name}' in course '{course.title}'.")
        return redirect('control_panel:enrollments_list')

    return render(request, 'control_panel/enrollments/create.html', {'students': students, 'courses': courses, 'active_nav': 'enrollments'})

@super_admin_required
def enrollment_cancel_view(request, pk):
    enrollment = get_object_or_404(Enrollment, pk=pk)
    if request.method == 'POST':
        enrollment.status = 'CANCELLED'
        enrollment.save()
        messages.warning(request, f"Cancelled enrollment for '{enrollment.student.full_name}'.")
    return redirect('control_panel:enrollments_list')



# --------------------------------------------------------------
# Roles & Permissions Management Views
# --------------------------------------------------------------

from users_roles.models import Role, Permission, RolePermission, RoleScope

@super_admin_required
def roles_list_view(request):
    q = request.GET.get('q', '').strip()
    role_type = request.GET.get('type', 'all')
    status = request.GET.get('status', 'all')

    qs = Role.objects.all()

    if role_type == 'system':
        qs = qs.filter(is_system_role=True)
    elif role_type == 'custom':
        qs = qs.filter(is_system_role=False)

    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))

    # Summary KPI
    total_roles = Role.objects.count()
    total_permissions = Permission.objects.count()
    active_roles = Role.objects.filter(is_active=True).count()
    assigned_users_count = User.objects.filter(assigned_role__isnull=False).count()

    roles_data = []
    for r in qs:
        perm_count = RolePermission.objects.filter(role=r).count()
        user_count = User.objects.filter(Q(assigned_role=r) | Q(role_code=r.code)).count()
        roles_data.append({
            'role': r,
            'perm_count': perm_count,
            'user_count': user_count,
        })

    context = {
        'active_nav': 'roles',
        'roles_data': roles_data,
        'total_roles': total_roles,
        'total_permissions': total_permissions,
        'active_roles': active_roles,
        'assigned_users_count': assigned_users_count,
        'q': q,
        'role_type': role_type,
        'status_filter': status,
    }
    return render(request, 'control_panel/roles/index.html', context)

RESERVED_ROLE_CODES = {'SUPER_ADMIN', 'SUPER_ADMIN_STAFF', 'ACADEMY_ADMIN', 'ACADEMY_STAFF', 'STUDENT', 'ADMIN', 'OWNER'}

@super_admin_required
def role_create_view(request):
    # Ensure default permissions are seeded in database
    ensure_default_permissions_seeded()

    # Determine assignable permissions based on creator privileges
    if request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser:
        assignable_perms = Permission.objects.all().order_by('module', 'code')
    else:
        granted_ids = UserPermissionOverride.objects.filter(user=request.user, is_granted=True).values_list('permission_id', flat=True)
        assignable_perms = Permission.objects.filter(id__in=granted_ids).order_by('module', 'code')

    modules_dict = {}
    for p in assignable_perms:
        mod = p.module or 'GENERAL'
        if mod not in modules_dict:
            modules_dict[mod] = []
        modules_dict[mod].append(p)

    errors = {}
    form_data = {}
    selected_perm_ids = []

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        is_active = request.POST.get('is_active') == 'true'
        selected_perm_ids = request.POST.getlist('permissions')

        # Auto generate role code from name
        code = name.upper().replace(' ', '_').replace('-', '_')
        code = ''.join(c for c in code if c.isalnum() or c == '_')

        form_data = {
            'name': name,
            'code': code,
            'description': description,
            'is_active': is_active,
        }

        if not name:
            errors['name'] = "Role name is required."

        if code in RESERVED_ROLE_CODES:
            errors['code'] = f"Role code '{code}' is a reserved system code."
        elif Role.objects.filter(code=code).exists():
            errors['code'] = f"Role code '{code}' is already taken."

        # Privilege escalation check: cannot assign permissions creator does not possess
        assignable_ids = set(p.id for p in assignable_perms)
        invalid_assignments = [pid for pid in selected_perm_ids if pid not in [str(aid) for aid in assignable_ids]]
        if invalid_assignments and not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser):
            errors['permissions'] = "You cannot assign permissions that you do not personally possess."

        if not errors:
            from django.db import transaction
            with transaction.atomic():
                role = Role.objects.create(
                    name=name,
                    code=code,
                    description=description,
                    scope=RoleScope.ACADEMY,
                    is_active=is_active,
                    is_system_role=False
                )

                for perm_id in selected_perm_ids:
                    perm = Permission.objects.filter(pk=perm_id).first()
                    if perm and (perm.id in assignable_ids or request.user.role_code == SystemRoleCode.SUPER_ADMIN):
                        RolePermission.objects.create(role=role, permission=perm)

                AuditLog.objects.create(
                    actor=request.user,
                    actor_type='ADMIN',
                    action=AuditAction.PERMISSION_GRANTED,
                    category=AuditCategory.ROLE_PERMISSION,
                    target_type='Role',
                    target_id=str(role.id),
                    description=f"Created custom role '{role.name}' ({role.code}) with {len(selected_perm_ids)} permissions."
                )

                messages.success(request, f"Role '{role.name}' created successfully.")
                return redirect('control_panel:role_detail', pk=role.id)

    return render(request, 'control_panel/roles/create.html', {
        'active_nav': 'roles',
        'modules_dict': modules_dict,
        'scopes': RoleScope.choices,
        'errors': errors,
        'form_data': form_data,
        'selected_perm_ids': selected_perm_ids,
    })

@super_admin_required
def role_detail_view(request, pk):
    role = get_object_or_404(Role, pk=pk)
    role_perms = RolePermission.objects.filter(role=role).select_related('permission')
    assigned_perm_ids = set(rp.permission_id for rp in role_perms if rp.permission_id)

    all_permissions = Permission.objects.all().order_by('module', 'code')
    modules_dict = {}
    for p in all_permissions:
        mod = p.module or 'GENERAL'
        if mod not in modules_dict:
            modules_dict[mod] = []
        modules_dict[mod].append({
            'permission': p,
            'is_assigned': p.id in assigned_perm_ids
        })

    assigned_users = User.objects.filter(Q(assigned_role=role) | Q(role_code=role.code)).select_related('academy')

    context = {
        'active_nav': 'roles',
        'role': role,
        'modules_dict': modules_dict,
        'assigned_users': assigned_users,
        'perm_count': len(assigned_perm_ids),
        'user_count': assigned_users.count(),
    }
    return render(request, 'control_panel/roles/detail.html', context)

@super_admin_required
def role_edit_view(request, pk):
    role = get_object_or_404(Role, pk=pk)
    role_perms = RolePermission.objects.filter(role=role)
    assigned_perm_ids = set(rp.permission_id for rp in role_perms if rp.permission_id)

    all_permissions = Permission.objects.all().order_by('module', 'code')
    modules_dict = {}
    for p in all_permissions:
        mod = p.module or 'GENERAL'
        if mod not in modules_dict:
            modules_dict[mod] = []
        modules_dict[mod].append({
            'permission': p,
            'is_assigned': p.id in assigned_perm_ids
        })

    errors = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        scope = request.POST.get('scope', role.scope)
        is_active = request.POST.get('is_active') == 'true'
        selected_perm_ids = request.POST.getlist('permissions')

        if not name:
            errors['name'] = "Role name cannot be empty."

        if not errors:
            from django.db import transaction
            with transaction.atomic():
                role.name = name
                role.description = description
                if not role.is_system_role:
                    role.scope = scope
                role.is_active = is_active
                role.save()

                RolePermission.objects.filter(role=role).delete()
                for perm_id in selected_perm_ids:
                    perm = Permission.objects.filter(pk=perm_id).first()
                    if perm:
                        RolePermission.objects.create(role=role, permission=perm)

                messages.success(request, f"Role '{role.name}' updated successfully.")
                return redirect('control_panel:role_detail', pk=role.id)

    return render(request, 'control_panel/roles/edit.html', {
        'active_nav': 'roles',
        'role': role,
        'modules_dict': modules_dict,
        'scopes': RoleScope.choices,
        'errors': errors,
    })

@super_admin_required
def role_delete_view(request, pk):
    role = get_object_or_404(Role, pk=pk)
    assigned_users_count = User.objects.filter(Q(assigned_role=role) | Q(role_code=role.code)).count()

    if request.method == 'POST':
        if role.is_system_role:
            messages.error(request, f"System role '{role.name}' cannot be deleted.")
            return redirect('control_panel:role_detail', pk=role.id)

        if assigned_users_count > 0:
            messages.error(request, f"Role '{role.name}' is assigned to {assigned_users_count} users. Reassign users before deleting.")
            return redirect('control_panel:role_detail', pk=role.id)

        name = role.name
        role.delete()
        messages.success(request, f"Role '{name}' deleted successfully.")
        return redirect('control_panel:roles_list')

    return render(request, 'control_panel/roles/confirm_delete.html', {
        'active_nav': 'roles',
        'role': role,
        'assigned_users_count': assigned_users_count,
    })

@super_admin_required
def permissions_list_view(request):
    q = request.GET.get('q', '').strip()
    qs = Permission.objects.all().order_by('module', 'code')

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(module__icontains=q) | Q(description__icontains=q))

    modules_dict = {}
    for p in qs:
        mod = p.module or 'GENERAL'
        if mod not in modules_dict:
            modules_dict[mod] = []
        roles_count = RolePermission.objects.filter(permission=p).count()
        modules_dict[mod].append({
            'permission': p,
            'roles_count': roles_count
        })

    context = {
        'active_nav': 'roles',
        'modules_dict': modules_dict,
        'q': q,
        'total_permissions': qs.count(),
    }
    return render(request, 'control_panel/roles/permissions.html', context)

permissions_registry_view = permissions_list_view

# --------------------------------------------------------------
# Academy & Team Views
# --------------------------------------------------------------

@super_admin_required
def website_builder_list_view(request):
    configs = AcademyWebsiteConfig.objects.select_related('academy').all()
    return render(request, 'control_panel/websites/index.html', {'configs': configs, 'active_nav': 'website'})

@super_admin_required
def website_builder_edit_view(request, pk):
    config = get_object_or_404(AcademyWebsiteConfig, pk=pk)
    if request.method == 'POST':
        config.theme = request.POST.get('theme', config.theme)
        config.hero_headline = request.POST.get('hero_headline', config.hero_headline)
        config.is_published = request.POST.get('is_published') == 'true'
        config.save()
        messages.success(request, f"Website configuration for '{config.academy.name}' updated.")
        return redirect('control_panel:website_builder')

    return render(request, 'control_panel/websites/edit.html', {'config': config, 'active_nav': 'website'})



# --------------------------------------------------------------
# Super Admin Staff (Platform Level) Management Views
# --------------------------------------------------------------

from users_roles.models import UserPermissionOverride

@super_admin_required
def super_admin_staff_list_view(request):
    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all')

    qs = User.objects.filter(role_code=SystemRoleCode.SUPER_ADMIN_STAFF)

    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))

    paginator = Paginator(qs, 20)
    staff_page = paginator.get_page(request.GET.get('page'))

    staff_data = []
    for u in staff_page:
        perm_count = len(get_user_permissions(u))
        staff_data.append({
            'user': u,
            'perm_count': perm_count,
        })

    context = {
        'active_nav': 'super_admin_staff',
        'staff_data': staff_data,
        'staff_page': staff_page,
        'q': q,
        'status_filter': status_filter,
    }
    return render(request, 'control_panel/super_admin_staff/index.html', context)

EXCLUDED_STAFF_ROLES = {'SUPER_ADMIN', 'ACADEMY_ADMIN', 'ACADEMY_STAFF', 'STUDENT'}

@super_admin_required
def super_admin_staff_create_view(request):
    ensure_default_permissions_seeded()
    assignable_roles = Role.objects.filter(is_active=True).exclude(code__in=EXCLUDED_STAFF_ROLES).order_by('name')
    errors = {}
    form_data = {}

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        assigned_role_id = request.POST.get('assigned_role_id', '').strip()
        password = request.POST.get('password', '').strip() or 'Password123!'
        is_active = request.POST.get('is_active') == 'true'

        form_data = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'assigned_role_id': assigned_role_id,
            'is_active': is_active,
        }

        if not full_name:
            errors['full_name'] = "Full Name is required."
        if not email:
            errors['email'] = "Email Address is required."
        elif User.objects.filter(email__iexact=email).exists():
            errors['email'] = "A user with this email address already exists."

        assigned_role = None
        if not assigned_role_id:
            errors['assigned_role_id'] = "Select a valid staff role."
        else:
            assigned_role = Role.objects.filter(pk=assigned_role_id, is_active=True).exclude(code__in=EXCLUDED_STAFF_ROLES).first()
            if not assigned_role:
                errors['assigned_role_id'] = "Select a valid active staff role."

        # Privilege escalation check for creator
        if assigned_role and not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser):
            creator_perms = set(get_user_permissions(request.user))
            role_perm_codes = set(Permission.objects.filter(permission_roles__role=assigned_role).values_list('code', flat=True))
            if not role_perm_codes.issubset(creator_perms):
                errors['assigned_role_id'] = "You cannot assign a role with permissions greater than your own."

        if not errors:
            from django.db import transaction, IntegrityError
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        email=email,
                        password=password,
                        full_name=full_name,
                        phone=phone,
                        role_code=SystemRoleCode.SUPER_ADMIN_STAFF,
                        assigned_role=assigned_role,
                        is_staff=True,
                        is_active=is_active
                    )

                    AuditLog.objects.create(
                        actor=request.user,
                        actor_type='SUPER_ADMIN',
                        action=AuditAction.USER_CREATED,
                        category=AuditCategory.USER,
                        target_type='User',
                        target_id=str(user.id),
                        description=f"Created Super Admin Staff account '{user.email}' with role '{assigned_role.name}'."
                    )

                    messages.success(request, f"Super Admin Staff user '{user.email}' created successfully.")
                    return redirect('control_panel:super_admin_staff_detail', pk=user.id)
            except IntegrityError:
                errors['email'] = "A user with this email address already exists."

    return render(request, 'control_panel/super_admin_staff/create.html', {
        'active_nav': 'super_admin_staff',
        'assignable_roles': assignable_roles,
        'errors': errors,
        'form_data': form_data,
    })

@super_admin_required
def super_admin_staff_detail_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    user_perms = get_user_permissions(target_user)
    recent_logs = AuditLog.objects.filter(target_id=str(pk)).order_by('-occurred_at')[:10]

    context = {
        'active_nav': 'super_admin_staff',
        'target_user': target_user,
        'user_perms': user_perms,
        'recent_logs': recent_logs,
    }
    return render(request, 'control_panel/super_admin_staff/detail.html', context)

@super_admin_required
def super_admin_staff_edit_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    assignable_roles = Role.objects.filter(is_active=True).exclude(code__in=EXCLUDED_STAFF_ROLES).order_by('name')
    errors = {}

    if target_user.role_code == SystemRoleCode.SUPER_ADMIN and not request.user.is_superuser:
        messages.error(request, "Cannot edit primary Super Admin account.")
        return redirect('control_panel:super_admin_staff_list')

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        assigned_role_id = request.POST.get('assigned_role_id', '').strip()
        is_active = request.POST.get('is_active') == 'true'

        if not full_name:
            errors['full_name'] = "Full name cannot be empty."
        if not email:
            errors['email'] = "Email address cannot be empty."
        elif User.objects.filter(email=email).exclude(pk=pk).exists():
            errors['email'] = "Email address is already in use by another user."

        assigned_role = None
        if assigned_role_id:
            assigned_role = Role.objects.filter(pk=assigned_role_id, is_active=True).exclude(code__in=EXCLUDED_STAFF_ROLES).first()
            if not assigned_role:
                errors['assigned_role_id'] = "Select a valid active staff role."

        if not errors:
            target_user.full_name = full_name
            target_user.email = email
            target_user.phone = phone
            target_user.assigned_role = assigned_role
            target_user.is_active = is_active
            target_user.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.USER_ACTIVATED if is_active else AuditAction.USER_DEACTIVATED,
                category=AuditCategory.USER,
                target_type='User',
                target_id=str(target_user.id),
                description=f"Updated Super Admin Staff profile for '{target_user.email}' with role '{assigned_role.name if assigned_role else 'None'}'."
            )

            messages.success(request, f"Updated profile for '{target_user.email}'.")
            return redirect('control_panel:super_admin_staff_detail', pk=pk)

    return render(request, 'control_panel/super_admin_staff/edit.html', {
        'active_nav': 'super_admin_staff',
        'target_user': target_user,
        'assignable_roles': assignable_roles,
        'errors': errors,
    })

@super_admin_required
def super_admin_staff_permissions_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if target_user.role_code == SystemRoleCode.SUPER_ADMIN:
        messages.info(request, "Super Admin automatically possesses all platform permissions.")
        return redirect('control_panel:super_admin_staff_detail', pk=pk)

    overrides = UserPermissionOverride.objects.filter(user=target_user, is_granted=True)
    granted_perm_ids = set(o.permission_id for o in overrides if o.permission_id)

    all_permissions = Permission.objects.all().order_by('module', 'code')
    modules_dict = {}
    for p in all_permissions:
        mod = p.module or 'GENERAL'
        if mod not in modules_dict:
            modules_dict[mod] = []
        modules_dict[mod].append({
            'permission': p,
            'is_assigned': p.id in granted_perm_ids
        })

    if request.method == 'POST':
        selected_perm_ids = request.POST.getlist('permissions')
        from django.db import transaction
        with transaction.atomic():
            UserPermissionOverride.objects.filter(user=target_user).delete()
            for perm_id in selected_perm_ids:
                perm = Permission.objects.filter(pk=perm_id).first()
                if perm:
                    UserPermissionOverride.objects.create(user=target_user, permission=perm, is_granted=True)

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.PERMISSION_GRANTED,
                category=AuditCategory.USER,
                target_type='User',
                target_id=str(target_user.id),
                description=f"Updated granted permissions for Super Admin Staff '{target_user.email}'."
            )

            messages.success(request, f"Updated permissions for '{target_user.email}'.")
            return redirect('control_panel:super_admin_staff_detail', pk=pk)

    return render(request, 'control_panel/super_admin_staff/permissions.html', {
        'active_nav': 'super_admin_staff',
        'target_user': target_user,
        'modules_dict': modules_dict,
    })

@super_admin_required
def super_admin_staff_enable_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        target_user.is_active = True
        target_user.save()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            action=AuditAction.USER_ACTIVATED,
            category=AuditCategory.USER,
            target_type='User',
            target_id=str(pk),
            description=f"Enabled Super Admin Staff account '{target_user.email}'."
        )
        messages.success(request, f"Account '{target_user.email}' enabled successfully.")
    return redirect('control_panel:super_admin_staff_list')

@super_admin_required
def super_admin_staff_disable_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if target_user.role_code == SystemRoleCode.SUPER_ADMIN:
        messages.error(request, "Primary Super Admin account cannot be disabled.")
        return redirect('control_panel:super_admin_staff_list')

    if request.method == 'POST':
        target_user.is_active = False
        target_user.save()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            action=AuditAction.USER_DEACTIVATED,
            category=AuditCategory.USER,
            target_type='User',
            target_id=str(pk),
            description=f"Disabled Super Admin Staff account '{target_user.email}'."
        )
        messages.warning(request, f"Account '{target_user.email}' has been disabled.")
    return redirect('control_panel:super_admin_staff_list')

@super_admin_required
def super_admin_staff_delete_view(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    if target_user.role_code == SystemRoleCode.SUPER_ADMIN:
        messages.error(request, "Primary Super Admin account cannot be deleted.")
        return redirect('control_panel:super_admin_staff_list')

    if request.method == 'POST':
        email = target_user.email
        target_user.delete()
        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            action=AuditAction.USER_DEACTIVATED,
            category=AuditCategory.USER,
            target_type='User',
            target_id=str(pk),
            description=f"Deleted Super Admin Staff account '{email}'."
        )
        messages.success(request, f"Staff account '{email}' deleted.")
        return redirect('control_panel:super_admin_staff_list')

    return render(request, 'control_panel/super_admin_staff/confirm_delete.html', {
        'active_nav': 'super_admin_staff',
        'target_user': target_user,
    })

# --------------------------------------------------------------
# System, Support, Audit, Websites & Settings Views
# --------------------------------------------------------------

@super_admin_required
def staff_list_view(request):
    return redirect('control_panel:super_admin_staff_list')

@super_admin_required
def staff_create_view(request):
    return redirect('control_panel:super_admin_staff_create')

@super_admin_required
def system_health_view(request):
    return redirect('control_panel:dashboard')

@super_admin_required
def background_jobs_view(request):
    return redirect('control_panel:dashboard')

# Websites Management Views
@super_admin_required
def website_builder_list_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'websites.view')):
        return render(request, 'control_panel/403.html', status=403)

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all').strip()

    academies = Academy.objects.all()
    if q:
        academies = academies.filter(
            Q(name__icontains=q) |
            Q(slug__icontains=q) |
            Q(email__icontains=q)
        )

    websites_list = []
    for ac in academies:
        cfg, _ = AcademyWebsiteConfig.objects.get_or_create(academy=ac)
        if status_filter == 'published' and not cfg.is_published:
            continue
        elif status_filter == 'unpublished' and cfg.is_published:
            continue

        websites_list.append({
            'academy': ac,
            'config': cfg,
        })

    paginator = Paginator(websites_list, 20)
    websites_page = paginator.get_page(request.GET.get('page'))

    can_edit = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'websites.update'))

    context = {
        'active_nav': 'website',
        'websites_page': websites_page,
        'q': q,
        'status_filter': status_filter,
        'can_edit': can_edit,
    }
    return render(request, 'control_panel/websites/index.html', context)

@super_admin_required
def website_builder_edit_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'websites.view')):
        return render(request, 'control_panel/403.html', status=403)

    academy = get_object_or_404(Academy, pk=pk)
    config, _ = AcademyWebsiteConfig.objects.get_or_create(academy=academy)

    can_edit = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'websites.update'))
    can_publish = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'websites.publish'))

    if request.method == 'POST':
        if not can_edit:
            return render(request, 'control_panel/403.html', status=403)

        header_title = request.POST.get('header_title', '').strip()
        hero_headline = request.POST.get('hero_headline', '').strip()
        hero_subheadline = request.POST.get('hero_subheadline', '').strip()
        custom_domain = request.POST.get('custom_domain', '').strip()
        theme = request.POST.get('theme', 'modern-dark').strip()
        
        if can_publish and 'is_published' in request.POST:
            config.is_published = request.POST.get('is_published') == 'true'

        config.header_title = header_title
        config.hero_headline = hero_headline
        config.hero_subheadline = hero_subheadline
        config.custom_domain = custom_domain
        config.theme = theme
        config.save()

        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            academy=academy,
            action=AuditAction.ACADEMY_UPDATED,
            category=AuditCategory.SYSTEM,
            target_type='AcademyWebsiteConfig',
            target_id=str(config.id),
            description=f"Updated website configuration for '{academy.name}' (Published: {config.is_published})."
        )

        messages.success(request, f"Website configuration for '{academy.name}' saved successfully.")
        return redirect('control_panel:website_builder_edit', pk=pk)

    context = {
        'active_nav': 'website',
        'academy': academy,
        'config': config,
        'can_edit': can_edit,
        'can_publish': can_publish,
    }
    return render(request, 'control_panel/websites/edit.html', context)

# Audit Logs Management View
@super_admin_required
def audit_logs_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'audit_logs.view')):
        return render(request, 'control_panel/403.html', status=403)

    q = request.GET.get('q', '').strip()
    category_filter = request.GET.get('category', '').strip()

    qs = AuditLog.objects.select_related('actor', 'academy').all()

    if q:
        qs = qs.filter(
            Q(actor_display__icontains=q) |
            Q(actor__email__icontains=q) |
            Q(action__icontains=q) |
            Q(description__icontains=q) |
            Q(target_type__icontains=q) |
            Q(target_id__icontains=q)
        )

    if category_filter:
        qs = qs.filter(category=category_filter)

    qs = qs.order_by('-occurred_at')

    paginator = Paginator(qs, 30)
    audits_page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'audit',
        'audits_page': audits_page,
        'q': q,
        'category_filter': category_filter,
    }
    return render(request, 'control_panel/audit/index.html', context)

# Support Tickets Management Views
@super_admin_required
def support_tickets_list_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'support.view')):
        return render(request, 'control_panel/403.html', status=403)

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    priority_filter = request.GET.get('priority', '').strip()

    qs = SupportTicket.objects.select_related('academy', 'user').all()

    if q:
        qs = qs.filter(
            Q(ticket_number__icontains=q) |
            Q(subject__icontains=q) |
            Q(academy__name__icontains=q) |
            Q(user__email__icontains=q)
        )

    if status_filter:
        qs = qs.filter(status=status_filter)

    if priority_filter:
        qs = qs.filter(priority=priority_filter)

    qs = qs.order_by('-created_at')

    # Summary KPI
    total_tickets = SupportTicket.objects.count()
    open_tickets = SupportTicket.objects.filter(status='OPEN').count()
    in_progress_tickets = SupportTicket.objects.filter(status='IN_PROGRESS').count()
    resolved_tickets = SupportTicket.objects.filter(status='RESOLVED').count()

    paginator = Paginator(qs, 20)
    tickets_page = paginator.get_page(request.GET.get('page'))

    context = {
        'active_nav': 'support',
        'tickets_page': tickets_page,
        'q': q,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'total_tickets': total_tickets,
        'open_tickets': open_tickets,
        'in_progress_tickets': in_progress_tickets,
        'resolved_tickets': resolved_tickets,
    }
    return render(request, 'control_panel/support/index.html', context)

@super_admin_required
def support_ticket_detail_view(request, pk):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'support.view')):
        return render(request, 'control_panel/403.html', status=403)

    ticket = get_object_or_404(SupportTicket.objects.select_related('academy', 'user'), pk=pk)
    ticket_messages = TicketMessage.objects.filter(ticket=ticket).select_related('sender').order_by('created_at')

    can_reply = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'support.reply'))
    can_update = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'support.update'))

    context = {
        'active_nav': 'support',
        'ticket': ticket,
        'ticket_messages': ticket_messages,
        'can_reply': can_reply,
        'can_update': can_update,
    }
    return render(request, 'control_panel/support/detail.html', context)

@super_admin_required
def support_ticket_reply_view(request, pk):
    ticket = get_object_or_404(SupportTicket, pk=pk)

    can_reply = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'support.reply'))
    can_update = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'support.update'))

    if not (can_reply or can_update):
        return render(request, 'control_panel/403.html', status=403)

    if request.method == 'POST':
        msg_text = request.POST.get('message', '').strip()
        new_status = request.POST.get('status', ticket.status)
        is_internal = request.POST.get('is_internal_note') == 'true'

        if msg_text and can_reply:
            TicketMessage.objects.create(
                ticket=ticket,
                sender=request.user,
                is_internal_note=is_internal,
                message=msg_text
            )

        if can_update and new_status != ticket.status:
            old_status = ticket.status
            ticket.status = new_status
            ticket.save()

            AuditLog.objects.create(
                actor=request.user,
                actor_type='SUPER_ADMIN',
                action=AuditAction.ACADEMY_UPDATED,
                category=AuditCategory.SYSTEM,
                target_type='SupportTicket',
                target_id=str(ticket.id),
                description=f"Updated support ticket #{ticket.ticket_number} status from '{old_status}' to '{new_status}'."
            )

        messages.success(request, f"Ticket #{ticket.ticket_number} updated successfully.")

    return redirect('control_panel:support_ticket_detail', pk=pk)

# Global Settings Management View
@super_admin_required
def global_settings_view(request):
    if not (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'settings.view')):
        return render(request, 'control_panel/403.html', status=403)

    can_edit = (request.user.role_code == SystemRoleCode.SUPER_ADMIN or request.user.is_superuser or has_permission(request.user, 'settings.edit'))

    if request.method == 'POST':
        if not can_edit:
            return render(request, 'control_panel/403.html', status=403)

        keys = [
            'platform_name', 'support_email', 'support_phone',
            'default_timezone', 'sender_name', 'sender_email',
            'payment_provider', 'billing_currency'
        ]
        for k in keys:
            if k in request.POST:
                val = request.POST.get(k, '').strip()
                setting, _ = SystemSetting.objects.get_or_create(key=k)
                setting.value = val
                setting.save()

        AuditLog.objects.create(
            actor=request.user,
            actor_type='SUPER_ADMIN',
            action=AuditAction.SYSTEM_SETTINGS_UPDATED,
            category=AuditCategory.SYSTEM,
            target_type='SystemSetting',
            target_id='global',
            description="Updated global platform settings configuration."
        )

        messages.success(request, "Global system settings updated successfully.")
        return redirect('control_panel:global_settings')

    settings_dict = {s.key: s.value for s in SystemSetting.objects.all()}

    # Defaults if missing
    settings_dict.setdefault('platform_name', 'CubixSkill')
    settings_dict.setdefault('support_email', 'support@cubixskill.com')
    settings_dict.setdefault('support_phone', '+91 98765 43210')
    settings_dict.setdefault('default_timezone', 'Asia/Kolkata')
    settings_dict.setdefault('sender_name', 'CubixSkill Platform')
    settings_dict.setdefault('sender_email', 'noreply@cubixskill.com')
    settings_dict.setdefault('payment_provider', 'Stripe')
    settings_dict.setdefault('billing_currency', 'INR')

    context = {
        'active_nav': 'settings',
        'settings': settings_dict,
        'can_edit': can_edit,
    }
    return render(request, 'control_panel/settings/index.html', context)


# --------------------------------------------------------------
# Super Admin Storage Control & Billing Views
# --------------------------------------------------------------

@super_admin_required
def storage_control_view(request):
    """
    Platform-wide Storage Overview page (/storage/).
    """
    academies = Academy.objects.all().order_by('name')
    from storage.metering import StorageMeteringService, StorageBillingService
    from storage.models import StorageMonthlyBilling, StorageUsageEvent, AcademyStorageAccount
    from storage.utils import format_bytes

    now = timezone.now()
    current_period_str = f"{now.year:04d}-{now.month:02d}"

    academy_data = []
    total_platform_bytes = 0

    search = request.GET.get('search', '').strip().lower()

    for acad in academies:
        if search and search not in acad.name.lower() and search not in str(acad.id).lower():
            continue

        account = StorageMeteringService.get_or_create_account(acad.id)
        billing = StorageBillingService.close_billing_period(acad.id, year=now.year, month=now.month)

        total_platform_bytes += account.current_usage_bytes

        academy_data.append({
            'academy': acad,
            'current_bytes': account.current_usage_bytes,
            'current_display': format_bytes(account.current_usage_bytes),
            'peak_display': format_bytes(billing.peak_bytes),
            'uploaded_display': format_bytes(billing.total_uploaded_bytes),
            'deleted_display': format_bytes(billing.total_deleted_bytes),
            'byte_seconds': billing.total_byte_seconds,
            'gb_month': str(billing.billable_units_gb_month),
            'credits_calculated': billing.credits_calculated,
            'credits_charged': billing.credits_charged,
            'status': billing.status,
            'billing_id': str(billing.id)
        })

    context = {
        'active_nav': 'storage',
        'academy_data': academy_data,
        'total_platform_bytes': total_platform_bytes,
        'total_platform_display': format_bytes(total_platform_bytes),
        'current_period_str': current_period_str,
        'search': search,
    }
    return render(request, 'control_panel/storage/overview.html', context)


@super_admin_required
def academy_storage_detail_view(request, pk):
    """
    Academy Storage Detail page (/storage/<uuid:pk>/).
    """
    academy = get_object_or_404(Academy, pk=pk)
    from storage.metering import StorageMeteringService, StorageBillingService
    from storage.models import StorageUsageEvent, StorageUsageRollup, StorageMonthlyBilling, MediaFile, MediaStatus
    from storage.utils import format_bytes

    account = StorageMeteringService.get_or_create_account(academy.id)
    current_billing = StorageBillingService.close_billing_period(academy.id)
    StorageBillingService.build_daily_rollup(academy.id)

    events = StorageUsageEvent.objects.filter(academy_uuid=academy.id).order_by('-occurred_at')[:50]
    daily_rollups = StorageUsageRollup.objects.filter(academy_uuid=academy.id, interval_type='DAILY').order_by('-period_start')[:30]
    monthly_billings = StorageMonthlyBilling.objects.filter(academy_uuid=academy.id).order_by('-billing_period_start')
    active_files = MediaFile.objects.filter(academy_uuid=academy.id).exclude(status=MediaStatus.DELETED).order_by('-created_at')[:20]

    context = {
        'active_nav': 'storage',
        'academy': academy,
        'account': account,
        'current_display': format_bytes(account.current_usage_bytes),
        'current_billing': current_billing,
        'events': events,
        'daily_rollups': daily_rollups,
        'monthly_billings': monthly_billings,
        'active_files': active_files,
    }
    return render(request, 'control_panel/storage/academy_detail.html', context)


@super_admin_required
def storage_rates_view(request):
    """
    Super Admin Storage Credit Rate Management (/storage/rates/).
    """
    from credits.models import CreditRate
    from credits.services import CreditPricingService

    rate = CreditPricingService.get_rate('STORAGE_MONTHLY')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip() or rate.name
        credit_cost = request.POST.get('credit_cost', '').strip()
        description = request.POST.get('description', '').strip()

        try:
            from decimal import Decimal
            rate.name = name
            rate.description = description
            if credit_cost:
                rate.credit_cost = Decimal(credit_cost)
            rate.save()
            messages.success(request, f"Storage monthly rate updated successfully ({rate.credit_cost} Credits / GB / Month).")
        except Exception as err:
            messages.error(request, f"Failed to update storage rate: {err}")

        return redirect('control_panel:storage_rates')

    context = {
        'active_nav': 'storage',
        'rate': rate,
    }
    return render(request, 'control_panel/storage/rates.html', context)


@super_admin_required
def storage_events_view(request):
    """
    Super Admin Immutable Storage Usage Event Audit Ledger (/storage/events/).
    """
    from storage.models import StorageUsageEvent
    from storage.utils import format_bytes
    from django.core.paginator import Paginator

    qs = StorageUsageEvent.objects.all().order_by('-occurred_at')

    event_type = request.GET.get('event_type', '').strip()
    if event_type:
        qs = qs.filter(event_type=event_type)

    academy_id = request.GET.get('academy_id', '').strip()
    if academy_id:
        qs = qs.filter(academy_uuid=academy_id)

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    academies = Academy.objects.all().order_by('name')

    context = {
        'active_nav': 'storage',
        'page_obj': page_obj,
        'academies': academies,
        'selected_event_type': event_type,
        'selected_academy_id': academy_id,
    }
    return render(request, 'control_panel/storage/events.html', context)


@super_admin_required
def storage_billing_list_view(request):
    """
    Super Admin Monthly Storage Billing Records (/storage/billing/).
    """
    from storage.models import StorageMonthlyBilling, BillingStatus
    from django.core.paginator import Paginator

    qs = StorageMonthlyBilling.objects.all().order_by('-billing_period_start')

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    month_filter = request.GET.get('month', '').strip()
    if month_filter:
        qs = qs.filter(billing_period=month_filter)

    paginator = Paginator(qs, 30)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    statuses = BillingStatus.choices

    context = {
        'active_nav': 'storage',
        'page_obj': page_obj,
        'statuses': statuses,
        'selected_status': status_filter,
        'selected_month': month_filter,
    }
    return render(request, 'control_panel/storage/billing_list.html', context)


@super_admin_required
def storage_billing_detail_view(request, pk):
    """
    Super Admin Explainable Billing Detail page (/storage/billing/<uuid:pk>/).
    """
    from storage.models import StorageMonthlyBilling, StorageUsageEvent
    from storage.utils import format_bytes

    billing = get_object_or_404(StorageMonthlyBilling, pk=pk)
    academy = Academy.objects.filter(id=billing.academy_uuid).first()

    events = StorageUsageEvent.objects.filter(
        academy_uuid=billing.academy_uuid,
        occurred_at__gte=billing.billing_period_start,
        occurred_at__lte=billing.billing_period_end
    ).order_by('occurred_at')

    context = {
        'active_nav': 'storage',
        'billing': billing,
        'academy': academy,
        'events': events,
        'opening_display': format_bytes(billing.opening_bytes),
        'closing_display': format_bytes(billing.closing_bytes),
        'peak_display': format_bytes(billing.peak_bytes),
        'uploaded_display': format_bytes(billing.total_uploaded_bytes),
        'deleted_display': format_bytes(billing.total_deleted_bytes),
    }
    return render(request, 'control_panel/storage/billing_detail.html', context)


@super_admin_required
def storage_billing_retry_view(request, pk):
    """
    Action view to retry charging a pending/failed storage billing record.
    """
    from storage.models import StorageMonthlyBilling
    from storage.metering import StorageBillingService

    billing = get_object_or_404(StorageMonthlyBilling, pk=pk)
    updated = StorageBillingService.retry_pending_billing(billing)

    if updated.status == 'CHARGED':
        messages.success(request, f"Billing record for '{updated.billing_period}' charged successfully!")
    elif updated.status == 'INSUFFICIENT_CREDITS':
        messages.warning(request, f"Charge failed: Insufficient Credits in Academy wallet ({updated.error_message}).")
    else:
        messages.error(request, f"Charge failed: {updated.error_message}")

    return redirect('control_panel:storage_billing_detail', pk=pk)


@super_admin_required
def storage_streaming_view(request):
    """
    Super Admin configuration for HLS Adaptive Bitrate Profiles & Transcoding Settings.
    """
    from storage.models import StorageStreamingProfile

    if request.method == 'POST':
        profile_id = request.POST.get('profile_id')
        if profile_id:
            profile = get_object_or_404(StorageStreamingProfile, pk=profile_id)
            profile.video_bitrate_kbps = int(request.POST.get('video_bitrate_kbps', profile.video_bitrate_kbps))
            profile.audio_bitrate_kbps = int(request.POST.get('audio_bitrate_kbps', profile.audio_bitrate_kbps))
            profile.is_enabled = request.POST.get('is_enabled') == 'on'
            profile.save()
            messages.success(request, f"HLS profile '{profile.quality_label}' updated successfully.")
            return redirect('control_panel:storage_streaming')

    profiles = StorageStreamingProfile.objects.all().order_by('-height')
    context = {
        'active_nav': 'storage',
        'profiles': profiles,
    }
    return render(request, 'control_panel/storage/streaming.html', context)


@super_admin_required
def storage_processing_view(request):
    """
    Super Admin monitor for video transcoding job queue & retries.
    """
    from storage.models import MediaFile, ProcessingStatus
    from storage.tasks import process_video_transcoding_task
    from storage.transcoder import check_video_processor_available

    if request.method == 'POST':
        media_id = request.POST.get('media_id')
        if media_id:
            media_file = get_object_or_404(MediaFile, pk=media_id)
            media_file.processing_status = ProcessingStatus.QUEUED
            media_file.processing_error = ''
            media_file.save()
            try:
                process_video_transcoding_task.delay(str(media_file.id))
            except Exception as exc:
                messages.warning(request, f"Could not dispatch Celery task: {exc}")
            messages.success(request, f"Queued retry transcoding for '{media_file.original_filename}'.")
            return redirect('control_panel:storage_processing')

    ffmpeg_ok, ffprobe_ok = check_video_processor_available()
    videos = MediaFile.objects.filter(media_type='VIDEO').order_by('-created_at')[:50]
    context = {
        'active_nav': 'storage',
        'videos': videos,
        'ffmpeg_available': ffmpeg_ok,
        'ffprobe_available': ffprobe_ok,
    }
    return render(request, 'control_panel/storage/processing.html', context)


@super_admin_required
def email_jobs_view(request):
    """
    Super Admin root-level monitor for DB Outbox Email Jobs.
    """
    from emails.models import EmailJob, EmailJobStatus, EmailJobType
    from django.db.models import Q

    jobs = EmailJob.objects.all().order_by('-created_at')

    status_filter = request.GET.get('status')
    if status_filter:
        jobs = jobs.filter(status=status_filter)

    type_filter = request.GET.get('job_type')
    if type_filter:
        jobs = jobs.filter(job_type=type_filter)

    search = request.GET.get('search')
    if search:
        jobs = jobs.filter(
            Q(subject__icontains=search) | Q(reference_id__icontains=search) | Q(idempotency_key__icontains=search)
        )

    context = {
        'active_nav': 'email_jobs',
        'jobs': jobs[:100],
        'statuses': EmailJobStatus.choices,
        'types': EmailJobType.choices,
        'selected_status': status_filter or '',
        'selected_type': type_filter or '',
        'search': search or ''
    }
    return render(request, 'control_panel/email_jobs/list.html', context)


@super_admin_required
def email_job_retry_view(request, pk):
    """
    Super Admin action view to trigger audited retry for a failed EmailJob.
    """
    from emails.models import EmailJob, EmailJobStatus
    from emails.tasks import process_email_job_task

    job = get_object_or_404(EmailJob, pk=pk)
    if job.status in [EmailJobStatus.FAILED, EmailJobStatus.PENDING, EmailJobStatus.RETRY]:
        job.status = EmailJobStatus.QUEUED
        job.last_error = ''
        job.save(update_fields=['status', 'last_error'])
        process_email_job_task.delay(str(job.id))
        messages.success(request, f"Queued manual retry for EmailJob {job.id}.")
    else:
        messages.warning(request, f"EmailJob {job.id} status is '{job.status}' and cannot be retried.")

    return redirect('control_panel:email_jobs')


@super_admin_required
def system_tasks_view(request):
    """
    Super Admin operational dashboard for Redis connectivity, Celery Workers, and Beat health.
    """
    from django.core.cache import cache
    from emails.models import EmailJob, EmailJobStatus

    redis_healthy = False
    try:
        cache.set('_health_ping', 'pong', 5)
        redis_healthy = cache.get('_health_ping') == 'pong'
    except Exception:
        redis_healthy = False

    pending_email_jobs = EmailJob.objects.filter(status=EmailJobStatus.PENDING).count()
    processing_email_jobs = EmailJob.objects.filter(status=EmailJobStatus.PROCESSING).count()
    failed_email_jobs = EmailJob.objects.filter(status=EmailJobStatus.FAILED).count()
    sent_today = EmailJob.objects.filter(status=EmailJobStatus.SENT, completed_at__gte=timezone.now().replace(hour=0, minute=0, second=0)).count()

    context = {
        'active_nav': 'system_tasks',
        'redis_healthy': redis_healthy,
        'pending_email_jobs': pending_email_jobs,
        'processing_email_jobs': processing_email_jobs,
        'failed_email_jobs': failed_email_jobs,
        'sent_today': sent_today,
    }
    return render(request, 'control_panel/system/tasks.html', context)


