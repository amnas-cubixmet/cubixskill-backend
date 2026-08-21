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
    tags = StudentTagSerializer(many=True, read_only=True)
    profile_photo = MediaFileSerializer(read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            'id', 'user_id', 'user', 'student_code', 'display_name', 'date_of_birth', 'bio',
            'profile_photo', 'status', 'joined_at', 'tags'
        ]
        read_only_fields = ['id', 'user_id', 'student_code', 'joined_at']

class StudentCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')

class StudentSelfUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentProfile
        fields = ['display_name', 'date_of_birth', 'bio']
