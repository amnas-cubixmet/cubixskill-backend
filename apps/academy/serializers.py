from rest_framework import serializers
from academy.models import Academy
from storage.serializers import MediaFileSerializer

#--------------------------------------------------------------
# Academy Serializer
#--------------------------------------------------------------

class AcademySerializer(serializers.ModelSerializer):
    logo = MediaFileSerializer(read_only=True)
    favicon = MediaFileSerializer(read_only=True)

    class Meta:
        model = Academy
        fields = [
            'id', 'name', 'slug', 'email', 'phone', 'theme', 'theme_color',
            'logo', 'favicon', 'status', 'is_active', 'is_demo', 'hls_video_enabled',
            'personal_chat_file_upload_enabled', 'community_chat_file_upload_enabled',
            'demo_start_date', 'demo_expiry_date', 'access_start_date', 'access_end_date',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at']

#--------------------------------------------------------------
# Academy Provisioning Serializer
#--------------------------------------------------------------

class AcademyProvisionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')
    theme = serializers.CharField(max_length=50, required=False, default='default')
    theme_color = serializers.CharField(max_length=20, required=False, default='#3B82F6')
    status = serializers.CharField(required=False, default='ACTIVE')

    is_demo = serializers.BooleanField(default=False)
    demo_start_date = serializers.DateTimeField(required=False, allow_null=True, default=None)
    demo_expiry_date = serializers.DateTimeField(required=False, allow_null=True, default=None)

    access_start_date = serializers.DateTimeField(required=False, allow_null=True, default=None)
    access_end_date = serializers.DateTimeField(required=False, allow_null=True, default=None)

    admin_email = serializers.EmailField()
    admin_name = serializers.CharField(max_length=255)
    admin_phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')
    admin_password = serializers.CharField(max_length=128, required=False, default='Password123!')

    staff_members = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    features = serializers.DictField(required=False, default=dict)

