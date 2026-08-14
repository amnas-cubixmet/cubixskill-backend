from django.contrib import admin
from website.models import WebsiteSettings

# --------------------------------------------------------------
# Website Admin Registration
# --------------------------------------------------------------

@admin.register(WebsiteSettings)
class WebsiteSettingsAdmin(admin.ModelAdmin):
    list_display = ['academy', 'home_hero_title', 'courses_title', 'contact_title', 'updated_at']
    search_fields = ['academy__name', 'academy__slug', 'home_hero_title']
    readonly_fields = ['updated_at']
