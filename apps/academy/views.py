from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from academy.models import Academy
from academy.serializers import AcademySerializer
from core.permissions import CanAccessAcademyPermission
from core.utils import api_response

#--------------------------------------------------------------
# Academy ViewSet
#--------------------------------------------------------------

class AcademyViewSet(viewsets.ModelViewSet):
    serializer_class = AcademySerializer
    permission_classes = [permissions.IsAuthenticated, CanAccessAcademyPermission]

    def get_queryset(self):
        user = self.request.user
        if user.role_code in ['SUPER_ADMIN', 'SUPER_ADMIN_STAFF']:
            return Academy.objects.all()
        if user.academy:
            return Academy.objects.filter(id=user.academy.id)
        return Academy.objects.none()

    @action(detail=False, methods=['get'])
    def current(self, request):
        if not request.user.academy:
            return api_response(data=None, message="No academy linked to user.")
        serializer = self.get_serializer(request.user.academy)
        return api_response(data=serializer.data)

#--------------------------------------------------------------
# Academy Provisioning View (Super Admin Only)
#--------------------------------------------------------------

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.db import transaction
from academy.models import AcademyStatus
from academy.serializers import AcademyProvisionSerializer
from users_roles.models import User, SystemRoleCode
from core.utils import CubixSkillAPIException

class AcademyProvisionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role_code not in [SystemRoleCode.SUPER_ADMIN, SystemRoleCode.SUPER_ADMIN_STAFF]:
            raise CubixSkillAPIException("Only Super Admin can provision new Academies.", code="PERMISSION_DENIED")

        serializer = AcademyProvisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if User.objects.filter(email=data['admin_email']).exists():
            raise CubixSkillAPIException("An account with the admin email already exists.", code="ADMIN_USER_EXISTS")

        with transaction.atomic():
            academy = Academy.objects.create(
                name=data['name'],
                email=data['email'],
                phone=data.get('phone', ''),
                theme=data.get('theme', 'default'),
                theme_color=data.get('theme_color', '#3B82F6'),
                status=data.get('status', AcademyStatus.ACTIVE),
                is_demo=data.get('is_demo', False),
                demo_start_date=data.get('demo_start_date'),
                demo_expiry_date=data.get('demo_expiry_date'),
                access_start_date=data.get('access_start_date'),
                access_end_date=data.get('access_end_date'),
                feature_config=data.get('features', {})
            )

            admin_user = User.objects.create_user(
                email=data['admin_email'],
                password=data.get('admin_password', 'Password123!'),
                full_name=data['admin_name'],
                phone=data.get('admin_phone', ''),
                role_code=SystemRoleCode.ACADEMY_ADMIN,
                academy=academy,
                is_email_verified=True,
                password_setup_completed=True
            )

            created_staff = []
            for staff_data in data.get('staff_members', []):
                s_email = staff_data.get('email')
                s_name = staff_data.get('full_name') or staff_data.get('name')
                if s_email and s_name and not User.objects.filter(email=s_email).exists():
                    s_user = User.objects.create_user(
                        email=s_email,
                        password=staff_data.get('password', 'Password123!'),
                        full_name=s_name,
                        phone=staff_data.get('phone', ''),
                        role_code=SystemRoleCode.ACADEMY_STAFF,
                        academy=academy,
                        is_email_verified=True,
                        password_setup_completed=True
                    )
                    created_staff.append({
                        "id": str(s_user.id),
                        "email": s_user.email,
                        "full_name": s_user.full_name,
                        "role": s_user.role_code
                    })

            return api_response({
                "academy": {
                    "id": str(academy.id),
                    "name": academy.name,
                    "slug": academy.slug,
                    "status": academy.status,
                    "is_demo": academy.is_demo,
                    "demo_status": academy.get_demo_status()
                },
                "admin_user": {
                    "id": str(admin_user.id),
                    "email": admin_user.email,
                    "full_name": admin_user.full_name,
                    "role": admin_user.role_code
                },
                "staff_members": created_staff,
                "features": academy.get_enabled_features()
            }, message="Academy and users provisioned successfully.", status_code=status.HTTP_201_CREATED)

class AcademyProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        academy = request.user.academy
        if not academy:
            raise CubixSkillAPIException("No academy linked to current user.", code="ACADEMY_NOT_FOUND")
        serializer = AcademySerializer(academy)
        data = dict(serializer.data)
        data['features'] = academy.get_enabled_features()
        data['demo_status'] = academy.get_demo_status()
        return api_response(data=data)

    def patch(self, request):
        academy = request.user.academy
        if not academy:
            raise CubixSkillAPIException("No academy linked to current user.", code="ACADEMY_NOT_FOUND")
        serializer = AcademySerializer(academy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        data = dict(serializer.data)
        data['features'] = academy.get_enabled_features()
        data['demo_status'] = academy.get_demo_status()
        return api_response(data=data, message="Academy profile updated successfully.")


class AcademySettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        academy = request.user.academy
        if not academy:
            raise CubixSkillAPIException("No academy linked to current user.", code="ACADEMY_NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND)
        data = {
            "hls_video_enabled": academy.hls_video_enabled,
            "personal_chat_file_upload_enabled": academy.personal_chat_file_upload_enabled,
            "community_chat_file_upload_enabled": academy.community_chat_file_upload_enabled,
            "academy_id": str(academy.id),
        }
        return api_response(data=data)

    def patch(self, request):
        user = request.user
        academy = user.academy
        if not academy:
            raise CubixSkillAPIException("No academy linked to current user.", code="ACADEMY_NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND)

        allowed_roles = ['ACADEMY_ADMIN', 'SUPER_ADMIN', 'SUPER_ADMIN_STAFF']
        if user.role_code not in allowed_roles:
            if user.role_code == 'ACADEMY_STAFF':
                if not (user.has_perm('manage_settings') or user.has_perm('manage_media')):
                    raise CubixSkillAPIException("Permission denied: Staff user lacks settings permission.", code="PERMISSION_DENIED", status_code=status.HTTP_403_FORBIDDEN)
            else:
                raise CubixSkillAPIException("Permission denied: Only Academy Admins can modify settings.", code="PERMISSION_DENIED", status_code=status.HTTP_403_FORBIDDEN)

        update_fields = []
        if 'hls_video_enabled' in request.data:
            val = request.data['hls_video_enabled']
            if isinstance(val, str):
                val = val.lower() in ('true', '1', 'yes', 'on')
            academy.hls_video_enabled = bool(val)
            update_fields.append('hls_video_enabled')

            from storage.models import AcademyStorageAccount
            account = AcademyStorageAccount.objects.filter(academy_uuid=academy.id).first()
            if account and hasattr(account, 'hls_video_enabled'):
                account.hls_video_enabled = academy.hls_video_enabled
                account.save(update_fields=['hls_video_enabled'])

        if 'personal_chat_file_upload_enabled' in request.data:
            val = request.data['personal_chat_file_upload_enabled']
            if isinstance(val, str):
                val = val.lower() in ('true', '1', 'yes', 'on')
            academy.personal_chat_file_upload_enabled = bool(val)
            update_fields.append('personal_chat_file_upload_enabled')

        if 'community_chat_file_upload_enabled' in request.data:
            val = request.data['community_chat_file_upload_enabled']
            if isinstance(val, str):
                val = val.lower() in ('true', '1', 'yes', 'on')
            academy.community_chat_file_upload_enabled = bool(val)
            update_fields.append('community_chat_file_upload_enabled')

        if update_fields:
            academy.save(update_fields=update_fields)

        return api_response(data={
            "hls_video_enabled": academy.hls_video_enabled,
            "personal_chat_file_upload_enabled": academy.personal_chat_file_upload_enabled,
            "community_chat_file_upload_enabled": academy.community_chat_file_upload_enabled,
            "academy_id": str(academy.id),
        }, message="Academy settings updated successfully.")
