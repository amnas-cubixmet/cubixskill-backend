from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

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
    token = serializers.CharField(required=True, error_messages={'required': 'Reset token is required.'})
    new_password = serializers.CharField(required=True, min_length=8, error_messages={'required': 'New password is required.', 'min_length': 'Password must be at least 8 characters long.'})
    confirm_password = serializers.CharField(required=True, min_length=8, error_messages={'required': 'Confirm password is required.', 'min_length': 'Password must be at least 8 characters long.'})

    def validate(self, data):
        new_pass = data.get('new_password')
        confirm_pass = data.get('confirm_password')

        if new_pass != confirm_pass:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})

        if new_pass:
            try:
                validate_password(new_pass)
            except DjangoValidationError as e:
                raise serializers.ValidationError({"new_password": list(e.messages)})

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
