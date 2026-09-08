from core.utils import CubixSkillAPIException
from rest_framework import serializers
from users_roles.models import Permission, Role, RolePermission, SystemRoleCode, User

#--------------------------------------------------------------
# Permission Serializer
#--------------------------------------------------------------

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['id', 'name', 'code', 'module', 'description']

#--------------------------------------------------------------
# Role Permission Serializer
#--------------------------------------------------------------

class RolePermissionSerializer(serializers.ModelSerializer):
    permission = PermissionSerializer(read_only=True)

    class Meta:
        model = RolePermission
        fields = ['id', 'permission']

#--------------------------------------------------------------
# Role Serializer
#--------------------------------------------------------------

class RoleSerializer(serializers.ModelSerializer):
    permissions = RolePermissionSerializer(many=True, read_only=True, source='role_permissions')

    class Meta:
        model = Role
        fields = ['id', 'name', 'code', 'description', 'scope', 'is_system_role', 'is_active', 'permissions']
        read_only_fields = ['id', 'is_system_role']

#--------------------------------------------------------------
# User Serializer
#--------------------------------------------------------------

class UserSerializer(serializers.ModelSerializer):
    assigned_role_detail = RoleSerializer(source='assigned_role', read_only=True)
    assigned_course_ids = serializers.PrimaryKeyRelatedField(source='assigned_courses', many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'phone', 'role_code', 'assigned_role', 'assigned_role_detail',
            'course_access_scope', 'assigned_course_ids', 'academy',
            'is_active', 'is_email_verified', 'password_setup_completed', 'last_login', 'created_at'
        ]
        read_only_fields = ['id', 'is_email_verified', 'password_setup_completed', 'last_login', 'created_at']

#--------------------------------------------------------------
# User Create Serializer
#--------------------------------------------------------------

class UserCreateSerializer(serializers.ModelSerializer):
    course_ids = serializers.ListField(child=serializers.UUIDField(), required=False, write_only=True)

    class Meta:
        model = User
        fields = ['email', 'full_name', 'phone', 'role_code', 'assigned_role', 'course_access_scope', 'course_ids']

    def create(self, validated_data):
        course_ids = validated_data.pop('course_ids', [])
        request_user = self.context['request'].user
        role_code = validated_data.get('role_code', SystemRoleCode.ACADEMY_STAFF)

        if request_user.role_code not in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            if role_code in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
                raise CubixSkillAPIException("Cannot assign Super Admin roles.", code="PERMISSION_DENIED")
            validated_data['academy'] = request_user.academy

        user = super().create(validated_data)
        if course_ids and user.course_access_scope == 'SELECTED':
            user.assigned_courses.set(course_ids)
        return user

    def update(self, instance, validated_data):
        course_ids = validated_data.pop('course_ids', None)
        user = super().update(instance, validated_data)
        if course_ids is not None:
            if user.course_access_scope == 'SELECTED':
                user.assigned_courses.set(course_ids)
            else:
                user.assigned_courses.clear()
        return user
