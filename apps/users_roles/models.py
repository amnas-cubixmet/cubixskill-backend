from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from core.models import BaseModel, ActiveMixin

#--------------------------------------------------------------
# Role Scopes
#--------------------------------------------------------------

class RoleScope(models.TextChoices):
    PLATFORM = 'PLATFORM', 'Platform'
    ACADEMY = 'ACADEMY', 'Academy'
    STUDENT = 'STUDENT', 'Student'

class SystemRoleCode(models.TextChoices):
    SUPER_ADMIN = 'SUPER_ADMIN', 'Super Admin'
    SUPER_ADMIN_STAFF = 'SUPER_ADMIN_STAFF', 'Super Admin Staff'
    ACADEMY_ADMIN = 'ACADEMY_ADMIN', 'Academy Admin'
    ACADEMY_STAFF = 'ACADEMY_STAFF', 'Academy Staff'
    STUDENT = 'STUDENT', 'Student'

#--------------------------------------------------------------
# Role
#--------------------------------------------------------------

class Role(BaseModel, ActiveMixin):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.TextField(blank=True, default='')
    scope = models.CharField(max_length=20, choices=RoleScope.choices, default=RoleScope.ACADEMY)
    is_system_role = models.BooleanField(default=False)

    class Meta:
        db_table = 'roles'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


#--------------------------------------------------------------
# Role Permission
#--------------------------------------------------------------

class Permission(BaseModel):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=100, unique=True, db_index=True)  # e.g., courses.update
    module = models.CharField(max_length=50, default='GENERAL', db_index=True)
    description = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'permissions'
        ordering = ['code']

    def __str__(self):
        return self.code


#--------------------------------------------------------------
# Role Permission
#--------------------------------------------------------------

class RolePermission(BaseModel):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='role_permissions', null=True, blank=True)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='permission_roles', null=True, blank=True)

    class Meta:
        db_table = 'role_permissions'
        unique_together = ('role', 'permission')

#--------------------------------------------------------------
# User Management
#--------------------------------------------------------------

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email address is required.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role_code', SystemRoleCode.SUPER_ADMIN)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_email_verified', True)
        extra_fields.setdefault('password_setup_completed', True)
        return self.create_user(email, password, **extra_fields)


#--------------------------------------------------------------
# User
#--------------------------------------------------------------

class User(AbstractBaseUser, PermissionsMixin, BaseModel, ActiveMixin):
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=30, blank=True, default='')

    role_code = models.CharField(
        max_length=30,
        choices=SystemRoleCode.choices,
        default=SystemRoleCode.STUDENT,
        db_index=True
    )
    assigned_role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')

    academy = models.ForeignKey(
        'academy.Academy',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users'
    )

    is_staff = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    password_setup_completed = models.BooleanField(default=False)

    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} ({self.role_code})"

    @property
    def role(self):
        return self.role_code


#--------------------------------------------------------------
# User Permission Override
#--------------------------------------------------------------

class UserPermissionOverride(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='permission_overrides', null=True, blank=True)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, null=True, blank=True)
    is_granted = models.BooleanField(default=True)

    class Meta:
        db_table = 'user_permission_overrides'
        unique_together = ('user', 'permission')

def has_permission(user: User, permission_code: str) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False

    # Super Admin Unrestricted Override
    if user.role_code == SystemRoleCode.SUPER_ADMIN or user.is_superuser:
        return True

    # Check direct user permission override
    override = UserPermissionOverride.objects.filter(user=user, permission__code=permission_code).first()
    if override:
        return override.is_granted

    # Check assigned role permissions
    if user.assigned_role:
        return RolePermission.objects.filter(role=user.assigned_role, permission__code=permission_code).exists()

    # Fallback to role_code matching default permissions
    return Permission.objects.filter(
        code=permission_code,
        permission_roles__role__code=user.role_code
    ).exists()

def can_access_academy(user: User, academy) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.role_code == SystemRoleCode.SUPER_ADMIN or user.is_superuser:
        return True
    if user.role_code == SystemRoleCode.SUPER_ADMIN_STAFF:
        return has_permission(user, 'academy.view')
    if not user.academy:
        return False
    target_id = str(academy.id) if hasattr(academy, 'id') else str(academy)
    return str(user.academy.id) == target_id

def get_user_permissions(user: User) -> list:
    """
    Returns complete list of permission codes assigned to user.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return []

    if user.role_code == SystemRoleCode.SUPER_ADMIN or user.is_superuser:
        return sorted(list(Permission.objects.values_list('code', flat=True)))

    permissions = set()

    if user.assigned_role:
        role_perms = Permission.objects.filter(
            permission_roles__role=user.assigned_role
        ).values_list('code', flat=True)
        permissions.update(role_perms)

    sys_perms = Permission.objects.filter(
        permission_roles__role__code=user.role_code
    ).values_list('code', flat=True)
    permissions.update(sys_perms)

    overrides = UserPermissionOverride.objects.filter(user=user).select_related('permission')
    for ov in overrides:
        if ov.permission:
            if ov.is_granted:
                permissions.add(ov.permission.code)
            else:
                permissions.discard(ov.permission.code)

    return sorted(list(permissions))

def ensure_default_permissions_seeded():
    """
    Ensures all core CubixSkill Control Panel permissions are seeded in the database.
    """
    DEFAULT_PERMISSIONS = [
        # Academies
        ("View Academies", "academy.view", "Academies", "View academy list and details"),
        ("Create Academy", "academy.create", "Academies", "Create new academy"),
        ("Edit Academy", "academy.update", "Academies", "Update academy details"),
        ("Delete Academy", "academy.delete", "Academies", "Delete or deactivate academy"),

        # Students
        ("View Students", "students.view", "Students", "View student directory"),
        ("Create Student", "students.create", "Students", "Add new student account"),
        ("Edit Student", "students.edit", "Students", "Edit student profiles"),
        ("Delete Student", "students.delete", "Students", "Delete student accounts"),

        # Users
        ("View Users", "users.view", "Users", "View platform users"),
        ("Create User", "users.create", "Users", "Add new user account"),
        ("Edit User", "users.edit", "Users", "Edit user accounts"),
        ("Delete User", "users.delete", "Users", "Delete user accounts"),

        # Super Admin Staff
        ("View Staff", "staff.view", "Super Admin Staff", "View staff directory"),
        ("Create Staff", "staff.create", "Super Admin Staff", "Create staff accounts"),
        ("Edit Staff", "staff.edit", "Super Admin Staff", "Edit staff accounts"),
        ("Disable Staff", "staff.delete", "Super Admin Staff", "Disable staff accounts"),
        ("Manage Staff Permissions", "staff.manage_permissions", "Super Admin Staff", "Grant or revoke staff permissions"),

        # Roles & Permissions
        ("View Roles", "roles.view", "Roles & Permissions", "View custom roles"),
        ("Create Role", "roles.create", "Roles & Permissions", "Create custom roles"),
        ("Edit Role", "roles.edit", "Roles & Permissions", "Edit custom roles"),
        ("Delete Role", "roles.delete", "Roles & Permissions", "Delete custom roles"),
        ("Manage Permissions", "roles.manage_permissions", "Roles & Permissions", "Manage permissions matrix"),

        # Courses
        ("View Courses", "courses.view", "Courses", "View course catalog"),
        ("Create Course", "courses.create", "Courses", "Create new courses"),
        ("Edit Course", "courses.edit", "Courses", "Edit course details"),
        ("Delete Course", "courses.delete", "Courses", "Delete courses"),
        ("Publish Course", "courses.publish", "Courses", "Publish or unpublish courses"),

        # Enrollments
        ("View Enrollments", "enrollments.view", "Enrollments", "View course enrollments"),
        ("Create Enrollment", "enrollments.create", "Enrollments", "Enroll students"),
        ("Edit Enrollment", "enrollments.edit", "Enrollments", "Edit enrollment status"),
        ("Cancel Enrollment", "enrollments.cancel", "Enrollments", "Cancel or revoke enrollment"),

        # Plans & Pricing
        ("View Plans", "plans.view", "Plans & Pricing", "View subscription plans"),
        ("Create Plan", "plans.create", "Plans & Pricing", "Create subscription plans"),
        ("Edit Plan", "plans.edit", "Plans & Pricing", "Edit subscription plans"),
        ("Delete Plan", "plans.delete", "Plans & Pricing", "Delete subscription plans"),

        # Pricing
        ("View Pricing", "pricing.view", "Pricing", "View credit usage pricing rules"),
        ("Create Pricing", "pricing.create", "Pricing", "Create credit usage pricing rules"),
        ("Edit Pricing", "pricing.update", "Pricing", "Edit credit usage pricing rules"),
        ("Delete Pricing", "pricing.delete", "Pricing", "Delete credit usage pricing rules"),

        # Features
        ("View Features", "features.view", "Features", "View feature registry"),
        ("Edit Feature", "features.edit", "Features", "Configure feature toggles"),

        # Credits
        ("View Credits", "credits.view", "Credits", "View credit accounts & transactions"),
        ("Add Credits", "credits.add", "Credits", "Grant credits"),
        ("Deduct Credits", "credits.deduct", "Credits", "Deduct credits"),
        ("Adjust Credits", "credits.adjust", "Credits", "Adjust credit balances"),

        # Storage
        ("View Storage", "storage.view", "Storage", "View storage usage"),
        ("Manage Storage", "storage.manage", "Storage", "Configure storage billing"),

        # Payments
        ("View Payments", "payments.view", "Payments", "View orders and revenue"),
        ("Manage Payments", "payments.manage", "Payments", "Manage payment transactions"),
        ("Refund Payment", "payments.refund", "Payments", "Issue payment refunds"),

        # Media
        ("View Media", "media.view", "Media", "View media library"),
        ("Upload Media", "media.upload", "Media", "Upload media assets"),
        ("Delete Media", "media.delete", "Media", "Delete media assets"),

        # Reports
        ("View Reports", "reports.view", "Reports", "View platform analytics"),
        ("Export Reports", "reports.export", "Reports", "Export analytics data"),

        # Settings
        ("View Settings", "settings.view", "Settings", "View system settings"),
        ("Edit Settings", "settings.edit", "Settings", "Update system settings"),

        # Websites
        ("View Websites", "websites.view", "Websites", "View website configs"),
        ("Edit Websites", "websites.update", "Websites", "Edit website configs"),
        ("Publish Websites", "websites.publish", "Websites", "Publish/unpublish websites"),

        # Audit Logs
        ("View Audit Logs", "audit_logs.view", "Audit Logs", "View administrative audit logs"),

        # Support
        ("View Support", "support.view", "Support", "View support tickets"),
        ("Update Support", "support.update", "Support", "Update support ticket status"),
        ("Reply Support", "support.reply", "Support", "Reply to support tickets"),
    ]

    for name, code, module, desc in DEFAULT_PERMISSIONS:
        Permission.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'module': module,
                'description': desc,
            }
        )


