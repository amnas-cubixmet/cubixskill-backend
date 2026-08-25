from rest_framework import serializers
from students.models import StudentProfile, StudentGuardian, StudentDocument, StudentNote, StudentTag
from users_roles.serializers import UserSerializer
from storage.serializers import MediaFileSerializer

#--------------------------------------------------------------
# Student Tag Serializer
#--------------------------------------------------------------

class StudentTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentTag
        fields = ['id', 'name', 'description']

#--------------------------------------------------------------
# Student Guardian Serializer
#--------------------------------------------------------------

class StudentGuardianSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentGuardian
        fields = ['id', 'name', 'relationship', 'phone', 'email', 'is_primary']

#--------------------------------------------------------------
# Student Document Serializer
#--------------------------------------------------------------

class StudentDocumentSerializer(serializers.ModelSerializer):
    media_file = MediaFileSerializer(read_only=True)

    class Meta:
        model = StudentDocument
        fields = ['id', 'title', 'document_type', 'media_file', 'description', 'created_at']

#--------------------------------------------------------------
# Student Note Serializer
#--------------------------------------------------------------

class StudentNoteSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)

    class Meta:
        model = StudentNote
        fields = ['id', 'note', 'visibility', 'created_by_name', 'created_at']

#--------------------------------------------------------------
# Student Profile Serializers
#--------------------------------------------------------------

class StudentProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.UUIDField(source='user.id', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    full_name = serializers.CharField(source='user.full_name', read_only=True)
    enrollments_count = serializers.IntegerField(default=0, read_only=True)
    tags = StudentTagSerializer(many=True, read_only=True)
    profile_photo = MediaFileSerializer(read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            'id', 'user_id', 'user', 'email', 'phone', 'full_name', 'student_code', 'display_name',
            'date_of_birth', 'bio', 'profile_photo', 'status', 'joined_at', 'tags', 'enrollments_count'
        ]
        read_only_fields = ['id', 'user_id', 'student_code', 'joined_at', 'enrollments_count']

class StudentCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')
    date_of_birth = serializers.DateField(required=False, allow_null=True, default=None)
    bio = serializers.CharField(required=False, allow_blank=True, default='')
    status = serializers.CharField(required=False, default='ACTIVE')

class StudentUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, max_length=255)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=30)
    display_name = serializers.CharField(required=False, max_length=255)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    bio = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False)

class StudentSelfUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentProfile
        fields = ['display_name', 'date_of_birth', 'bio']

#--------------------------------------------------------------
# Student Custom Field Serializers
#--------------------------------------------------------------

from students.models import StudentCustomFieldDefinition, StudentCustomFieldValue

class StudentCustomFieldDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentCustomFieldDefinition
        fields = ['id', 'key', 'label', 'field_type', 'available_for_certificate', 'required', 'sort_order', 'is_active']
        read_only_fields = ['id']

class StudentCustomFieldValueSerializer(serializers.ModelSerializer):
    field_key = serializers.CharField(source='field_definition.key', read_only=True)
    field_label = serializers.CharField(source='field_definition.label', read_only=True)

    class Meta:
        model = StudentCustomFieldValue
        fields = ['id', 'field_definition', 'field_key', 'field_label', 'value']

