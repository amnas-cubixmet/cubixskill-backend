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
    if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
        return True

    # Check direct user permission override
    override = UserPermissionOverride.objects.filter(user=user, permission__code=permission_code).first()
    if override:
        return override.is_granted

    # Check role permissions
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
    if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
        return True
    if not user.academy:
        return False
    target_id = str(academy.id) if hasattr(academy, 'id') else str(academy)
    return str(user.academy.id) == target_id
