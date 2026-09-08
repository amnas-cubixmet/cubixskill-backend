from academy.models import Academy
from django.contrib import admin

#--------------------------------------------------------------
# Admin Configuration
#--------------------------------------------------------------

@admin.register(Academy)
class AcademyAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'email', 'phone', 'status', 'is_active', 'created_at')
    list_filter = ('status', 'is_active', 'created_at')
    search_fields = ('name', 'slug', 'email', 'phone')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('name',)
