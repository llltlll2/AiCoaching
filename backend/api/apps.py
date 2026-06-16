from django.apps import AppConfig
from django.db.backends.signals import connection_created
from django.dispatch import receiver


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        import os
        # Prevent scheduler from running multiple times in development mode with auto-reloader
        if os.environ.get('RUN_MAIN', None) != 'true':
            from api import scheduler
            scheduler.start()


@receiver(connection_created)
def configure_sqlite(sender, connection, **kwargs):
    """SQLiteの並行処理パフォーマンス向上のためのPRAGMA設定"""
    if connection.vendor == 'sqlite':
        cursor = connection.cursor()
        # WALモードの有効化 (書込と読込の同時並行化)
        cursor.execute('PRAGMA journal_mode=WAL;')
        # 同期化レベルをNORMALに変更 (ディスク書き込み待ちを減らし、高速化しつつ安全性維持)
        cursor.execute('PRAGMA synchronous=NORMAL;')
        # ロック競合時の最大待機時間（ミリ秒）を設定 (デフォルトは0〜5000msだが、10秒に延長)
        cursor.execute('PRAGMA busy_timeout=10000;')
