from rest_framework import serializers
from website.models import WebsiteSettings
from website.services import WebsiteService

# --------------------------------------------------------------
# Website Serializers
# Validates text settings and theme color formats.
# Enforces backend character limits.
# --------------------------------------------------------------

class WebsiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsiteSettings
        fields = [
            'home_hero_title',
            'home_hero_subtitle',
            'courses_title',
            'courses_description',
            'contact_title',
            'contact_description',
            'updated_at',
        ]
        read_only_fields = ['updated_at']

class UpdateWebsiteSettingsSerializer(serializers.Serializer):
    home_hero_title = serializers.CharField(max_length=100, required=False)
    home_hero_subtitle = serializers.CharField(max_length=250, required=False)
    courses_title = serializers.CharField(max_length=100, required=False)
    courses_description = serializers.CharField(max_length=500, required=False)
    contact_title = serializers.CharField(max_length=100, required=False)
    contact_description = serializers.CharField(max_length=500, required=False)

class UpdateThemeColorSerializer(serializers.Serializer):
    theme_color = serializers.CharField(max_length=10)

    def validate_theme_color(self, value):
        return WebsiteService.validate_hex_color(value)
