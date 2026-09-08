from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    label = 'core'

class AcademyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academy'
    label = 'academy'

class AuthenticationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'authentication'
    label = 'authentication'

class UsersRolesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users_roles'
    label = 'users_roles'

class FeaturesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'features'
    label = 'features'

class PlansEntitlementsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'plans_entitlements'
    label = 'plans_entitlements'

class CoursesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'courses'
    label = 'courses'

class ModulesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'modules'
    label = 'modules'

class LessonsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'lessons'
    label = 'lessons'

class StorageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'storage'
    label = 'storage'

class StudentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'students'
    label = 'students'

class EnrollmentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'enrollments'
    label = 'enrollments'

class LearningProgressConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'learning_progress'
    label = 'learning_progress'

class CertificatesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'certificates'
    label = 'certificates'

class LiveClassesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'live_classes'
    label = 'live_classes'

class DiscussionsChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'discussions_chat'
    label = 'discussions_chat'

class LeadsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'leads'
    label = 'leads'

class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payments'
    label = 'payments'

class CreditsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'credits'
    label = 'credits'

class WebsiteConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'website'
    label = 'website'

class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notifications'
    label = 'notifications'

class AnalyticsReportsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analytics_reports'
    label = 'analytics_reports'

class AuditLogsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'audit_logs'
    label = 'audit_logs'

class SettingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'settings'
    label = 'settings'
