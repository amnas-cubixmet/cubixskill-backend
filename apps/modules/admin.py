from django.contrib import admin
from modules.models import Module

#--------------------------------------------------------------
# Admin Configuration
#--------------------------------------------------------------

@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order_index', 'duration_minutes', 'is_demo', 'is_active', 'created_at')
    list_filter = ('is_active', 'is_demo', 'course__academy')
    search_fields = ('title', 'description', 'course__title')
    ordering = ('course', 'order_index')
