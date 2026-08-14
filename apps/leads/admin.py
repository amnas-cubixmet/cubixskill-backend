from django.contrib import admin
from leads.models import (
    Lead,
    LeadCourseInterest,
    LeadAssignment,
    LeadFollowUp,
    LeadNote,
    LeadActivity,
    LeadTag,
    LeadImportJob,
)

# --------------------------------------------------------------
# 1. Lead Admin & Inlines
# --------------------------------------------------------------

class LeadCourseInterestInline(admin.TabularInline):
    model = LeadCourseInterest
    extra = 0

class LeadFollowUpInline(admin.TabularInline):
    model = LeadFollowUp
    extra = 0

class LeadNoteInline(admin.TabularInline):
    model = LeadNote
    extra = 0

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'phone', 'academy', 'status', 'priority', 'source', 'assigned_to', 'created_at')
    list_filter = ('status', 'priority', 'source', 'academy')
    search_fields = ('full_name', 'email', 'phone', 'email_normalized', 'phone_normalized')
    inlines = [LeadCourseInterestInline, LeadFollowUpInline, LeadNoteInline]

# --------------------------------------------------------------
# 2. Lead Assignment Admin
# --------------------------------------------------------------

@admin.register(LeadAssignment)
class LeadAssignmentAdmin(admin.ModelAdmin):
    list_display = ('lead', 'assigned_to', 'assigned_by', 'assigned_at', 'unassigned_at')
    list_filter = ('assigned_at',)
    search_fields = ('lead__full_name', 'assigned_to__email')

# --------------------------------------------------------------
# 3. Lead Follow-Up Admin
# --------------------------------------------------------------

@admin.register(LeadFollowUp)
class LeadFollowUpAdmin(admin.ModelAdmin):
    list_display = ('lead', 'follow_up_type', 'scheduled_at', 'status', 'assigned_to', 'completed_at')
    list_filter = ('follow_up_type', 'status', 'scheduled_at')
    search_fields = ('lead__full_name', 'notes', 'outcome')

# --------------------------------------------------------------
# 4. Lead Note Admin
# --------------------------------------------------------------

@admin.register(LeadNote)
class LeadNoteAdmin(admin.ModelAdmin):
    list_display = ('lead', 'author', 'is_pinned', 'created_at')
    list_filter = ('is_pinned', 'created_at')
    search_fields = ('lead__full_name', 'content')

# --------------------------------------------------------------
# 5. Lead Activity Admin
# --------------------------------------------------------------

@admin.register(LeadActivity)
class LeadActivityAdmin(admin.ModelAdmin):
    list_display = ('lead', 'activity_type', 'performed_by', 'occurred_at')
    list_filter = ('activity_type', 'occurred_at')
    search_fields = ('lead__full_name', 'activity_type')

# --------------------------------------------------------------
# 6. Lead Tag Admin
# --------------------------------------------------------------

@admin.register(LeadTag)
class LeadTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'academy', 'color')
    search_fields = ('name',)

# --------------------------------------------------------------
# 7. Lead Import Job Admin
# --------------------------------------------------------------

@admin.register(LeadImportJob)
class LeadImportJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'academy', 'uploaded_by', 'status', 'total_rows', 'created_count', 'updated_count', 'failed_count', 'created_at')
    list_filter = ('status', 'created_at')
