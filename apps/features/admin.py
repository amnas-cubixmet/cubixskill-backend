from django.contrib import admin
from features.models import CourseFeature, Feature

#--------------------------------------------------------------
# Admin
#--------------------------------------------------------------

@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'scope', 'is_active', 'sort_order')
    list_filter = ('category', 'scope', 'is_active')
    search_fields = ('name', 'code', 'frontend_key')
    ordering = ('sort_order', 'name')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(CourseFeature)
class CourseFeatureAdmin(admin.ModelAdmin):
    list_display = ('course', 'feature', 'is_enabled', 'enabled_by', 'enabled_at', 'disabled_at')
    list_filter = ('is_enabled', 'feature')
    search_fields = ('course__title', 'feature__code', 'feature__name')
    readonly_fields = ('id', 'enabled_at', 'created_at', 'updated_at')
