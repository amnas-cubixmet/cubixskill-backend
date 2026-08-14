from django.contrib import admin
from courses.models import Course, CourseCategory, CourseModule

#--------------------------------------------------------------
# Admin Configurations
#--------------------------------------------------------------

@admin.register(CourseCategory)
class CourseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'academy', 'order_index', 'is_active')
    list_filter = ('academy', 'is_active')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'academy', 'level', 'price', 'is_free', 'status', 'visibility', 'is_published')
    list_filter = ('status', 'visibility', 'level', 'is_free', 'is_published', 'academy')
    search_fields = ('title', 'slug', 'subtitle', 'short_description')
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('-created_at',)

@admin.register(CourseModule)
class CourseModuleAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order_index', 'is_active')
    list_filter = ('is_active', 'course__academy')
    search_fields = ('title', 'course__title')
