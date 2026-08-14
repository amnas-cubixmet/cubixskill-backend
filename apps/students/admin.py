from django.contrib import admin
from students.models import StudentProfile, StudentGuardian, StudentDocument, StudentNote, StudentTag

#--------------------------------------------------------------
# Admin Configurations
#--------------------------------------------------------------

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('student_code', 'display_name', 'user_email', 'status', 'joined_at')
    list_filter = ('status', 'joined_at')
    search_fields = ('student_code', 'display_name', 'user__email', 'user__phone')
    ordering = ('-joined_at',)

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

@admin.register(StudentGuardian)
class StudentGuardianAdmin(admin.ModelAdmin):
    list_display = ('name', 'relationship', 'phone', 'student', 'is_primary')
    list_filter = ('is_primary', 'relationship')
    search_fields = ('name', 'phone', 'student__display_name')

@admin.register(StudentDocument)
class StudentDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'document_type', 'student', 'uploaded_by', 'created_at')
    list_filter = ('document_type', 'created_at')
    search_fields = ('title', 'student__display_name')

@admin.register(StudentNote)
class StudentNoteAdmin(admin.ModelAdmin):
    list_display = ('student', 'visibility', 'created_by', 'created_at')
    list_filter = ('visibility', 'created_at')

@admin.register(StudentTag)
class StudentTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'academy')
    list_filter = ('academy',)
    search_fields = ('name',)
