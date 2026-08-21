from django.apps import AppConfig

class FeesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fees'
    verbose_name = 'Student Fee Collection Management'

    def ready(self):
        try:
            import fees.signals  # noqa
        except ImportError:
            pass
