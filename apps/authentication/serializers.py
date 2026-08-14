from rest_framework import serializers

#--------------------------------------------------------------
# Registration Serializer
#--------------------------------------------------------------

class RegisterStudentSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')
    academy_slug = serializers.CharField(max_length=255)

class RegisterAcademySerializer(serializers.Serializer):
    academy_name = serializers.CharField(max_length=255)
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')


#--------------------------------------------------------------
# Login Serializer
#--------------------------------------------------------------

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

#--------------------------------------------------------------
# Token Action Serializers
#--------------------------------------------------------------

class TokenVerifySerializer(serializers.Serializer):
    token = serializers.CharField()

#--------------------------------------------------------------
# Password Setup Serializer
#--------------------------------------------------------------

class PasswordSetupSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8)
    confirm_password = serializers.CharField(min_length=8)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data

#--------------------------------------------------------------
# Forgot Password Serializer
#--------------------------------------------------------------

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

#--------------------------------------------------------------
# Password Reset Serializer
#--------------------------------------------------------------

class PasswordResetSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8)
    confirm_password = serializers.CharField(min_length=8)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data

#--------------------------------------------------------------
# Authenticated Password Change Serializer
#--------------------------------------------------------------

class AuthenticatedPasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=8)
    confirm_password = serializers.CharField(min_length=8)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data
