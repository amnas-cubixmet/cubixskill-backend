from django.db.models import Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from users_roles.models import (
    Permission,
    Role,
    RolePermission,
    RoleScope,
    SystemRoleCode,
    User,
)
from users_roles.serializers import (
    PermissionSerializer,
    RoleSerializer,
    UserCreateSerializer,
    UserSerializer,
)

#--------------------------------------------------------------
# User ViewSet for Staff & Tenant Users Management
#--------------------------------------------------------------

class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            qs = User.objects.all()
        else:
            # Tenant boundary isolation: Current Academy staff & users only
            qs = User.objects.filter(academy=user.academy)

        # Filtering parameters
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role_code=role)

        status_param = self.request.query_params.get('status')
        if status_param == 'Active':
            qs = qs.filter(is_active=True)
        elif status_param == 'Inactive':
            qs = qs.filter(is_active=False)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(email__icontains=search) |
                Q(full_name__icontains=search) |
                Q(phone__icontains=search)
            )

        return qs.order_by('-created_at')

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        if request.method == 'PATCH':
            serializer = UserSerializer(request.user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        """
        Returns metric aggregates for current Academy staff members.
        """
        user = request.user
        qs = User.objects.filter(academy=user.academy) if user.role_code not in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF] else User.objects.all()
        
        staff_qs = qs.exclude(role_code=SystemRoleCode.STUDENT)
        total = staff_qs.count()
        active = staff_qs.filter(is_active=True).count()
        inactive = staff_qs.filter(is_active=False).count()
        admins = staff_qs.filter(role_code=SystemRoleCode.ACADEMY_ADMIN).count()
        staff_count = staff_qs.filter(role_code=SystemRoleCode.ACADEMY_STAFF).count()

        return Response({
            "total": total,
            "active": active,
            "inactive": inactive,
            "admins": admins,
            "staff": staff_count,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        target_user = self.get_object()
        target_user.is_active = True
        target_user.save(update_fields=['is_active'])
        return Response({'status': f'User {target_user.email} activated.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        target_user = self.get_object()
        
        # Last Admin Protection
        if target_user.role_code == SystemRoleCode.ACADEMY_ADMIN and target_user.is_active:
            active_admin_count = User.objects.filter(
                academy=target_user.academy,
                role_code=SystemRoleCode.ACADEMY_ADMIN,
                is_active=True
            ).count()
            if active_admin_count <= 1:
                raise ValidationError({"detail": "At least one active Academy Admin is required for this Academy."})

        target_user.is_active = False
        target_user.save(update_fields=['is_active'])
        return Response({'status': f'User {target_user.email} deactivated.'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def resend_invitation(self, request, pk=None):
        target_user = self.get_object()
        from emails.outbox_service import EmailJobService
        academy_name = target_user.academy.name if target_user.academy else "CubixSkill Academy"
        job = EmailJobService.create_transactional_job(
            recipient_email=target_user.email,
            subject=f"Staff Invitation – {academy_name}",
            template_name="staff_invitation",
            context={
                "staff_name": target_user.full_name or target_user.email,
                "academy_name": academy_name,
                "login_url": "http://localhost:5173/login",
            },
            academy_uuid=target_user.academy_id if hasattr(target_user, 'academy_id') else None,
            recipient_user_uuid=target_user.id,
            recipient_name=target_user.full_name or target_user.email
        )
        return Response({'message': f'Invitation email queued for {target_user.email}.', 'job_id': str(job.id)}, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# Role ViewSet
#--------------------------------------------------------------

class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role_code not in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            # Filter out Super Admin platform roles for Academy users
            return Role.objects.exclude(code__in=['SUPER_ADMIN', 'SUPER_ADMIN_STAFF'])
        return Role.objects.all()

    def create(self, request, *args, **kwargs):
        name = request.data.get('name', '').strip()
        description = request.data.get('description', '').strip()
        permission_codes = request.data.get('permission_codes', [])

        if not name:
            raise ValidationError({"name": "Role name is required."})

        code = request.data.get('code') or name.upper().replace(' ', '_')
        role, created = Role.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'description': description,
                'scope': RoleScope.ACADEMY,
                'is_system_role': False,
            }
        )
        if not created:
            role.name = name
            role.description = description
            role.save()

        if permission_codes:
            RolePermission.objects.filter(role=role).delete()
            perms = Permission.objects.filter(code__in=permission_codes)
            for perm in perms:
                RolePermission.objects.create(role=role, permission=perm)

        serializer = self.get_serializer(role)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def permissions(self, request, pk=None):
        role = self.get_object()
        permission_ids = request.data.get('permission_ids', [])
        RolePermission.objects.filter(role=role).delete()
        for p_id in permission_ids:
            try:
                perm = Permission.objects.get(id=p_id)
                RolePermission.objects.create(role=role, permission=perm)
            except Permission.DoesNotExist:
                continue
        return Response({'status': 'Role permissions updated successfully.'}, status=status.HTTP_200_OK)

#--------------------------------------------------------------
# Permission ViewSet
#--------------------------------------------------------------

class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def registry(self, request):
        perms = Permission.objects.all()
        grouped = {}
        for p in perms:
            mod = p.module or 'General'
            if mod not in grouped:
                grouped[mod] = []
            grouped[mod].append({
                'id': str(p.id),
                'code': p.code,
                'name': p.name,
                'description': p.description,
            })
        result = [{'module': k, 'permissions': v} for k, v in grouped.items()]
        return Response(result, status=status.HTTP_200_OK)
