from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        import os
        # Prevent scheduler from running multiple times in development mode with auto-reloader
        if os.environ.get('RUN_MAIN', None) != 'true':
            from api import scheduler
            scheduler.start()
