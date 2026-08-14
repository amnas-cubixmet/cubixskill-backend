from rest_framework import serializers
from users_roles.models import User, Role, Permission, RolePermission, SystemRoleCode
from core.utils import CubixSkillAPIException


#--------------------------------------------------------------
# Permission Serializer
#--------------------------------------------------------------

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['id', 'name', 'code', 'module', 'description']

#--------------------------------------------------------------
# Permission Serializer
#--------------------------------------------------------------

class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True, source='role_permissions')

    class Meta:
        model = Role
        fields = ['id', 'name', 'code', 'description', 'scope', 'is_system_role', 'is_active', 'permissions']
        read_only_fields = ['id', 'is_system_role']

#--------------------------------------------------------------
# User Serializer
#--------------------------------------------------------------

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'phone', 'role_code', 'assigned_role', 'academy',
            'is_active', 'is_email_verified', 'password_setup_completed', 'last_login', 'created_at'
        ]
        read_only_fields = ['id', 'is_email_verified', 'password_setup_completed', 'last_login', 'created_at']

#--------------------------------------------------------------
# User Create Serializer
#--------------------------------------------------------------

class UserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'full_name', 'phone', 'role_code', 'assigned_role']

    def create(self, validated_data):
        request_user = self.context['request'].user
        role_code = validated_data.get('role_code', SystemRoleCode.ACADEMY_STAFF)

        # Prevent assigning roles above own authority
        if request_user.role_code not in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            if role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
                raise CubixSkillAPIException("Cannot assign Super Admin roles.", code="PERMISSION_DENIED")
            validated_data['academy'] = request_user.academy

        return super().create(validated_data)
