from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from users_roles.models import User, Role, Permission, RolePermission
from users_roles.serializers import UserSerializer, UserCreateSerializer, RoleSerializer, PermissionSerializer

#--------------------------------------------------------------
# User ViewSet
#--------------------------------------------------------------

class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role_code in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            return User.objects.all()
        # Tenant boundary isolation
        return User.objects.filter(academy=user.academy)

    @action(detail=False, methods=['get'])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        target_user = self.get_object()
        target_user.is_active = True
        target_user.save(update_fields=['is_active'])
        return Response({'status': f'User {target_user.email} activated.'})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        target_user = self.get_object()
        target_user.is_active = False
        target_user.save(update_fields=['is_active'])
        return Response({'status': f'User {target_user.email} deactivated.'})

#--------------------------------------------------------------
# Role ViewSet
#--------------------------------------------------------------

class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated]

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
        return Response({'status': 'Role permissions updated successfully.'})

#--------------------------------------------------------------
# Permission ViewSet
#--------------------------------------------------------------

class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
