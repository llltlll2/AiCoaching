from apscheduler.schedulers.background import BackgroundScheduler
import os
from plyer import notification
from api import google_services

# グローバルなスケジューラーインスタンス
_scheduler = None

def schedule_next_reminder():
    global _scheduler
    if not _scheduler:
        return
        
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    if not spreadsheet_id:
        return
        
    # 学習記録から平均完了時間を算出
    avg_hour, avg_minute = google_services.get_average_study_time(spreadsheet_id)
    print(f"Dynamic Reminder: Next reminder scheduled for {avg_hour:02d}:{avg_minute:02d}")
    
    # 既存のジョブがあれば削除
    if _scheduler.get_job('daily_reminder'):
        _scheduler.remove_job('daily_reminder')
        
    # 新しい時間でジョブを再登録
    _scheduler.add_job(
        check_daily_record, 
        'cron', 
        hour=avg_hour, 
        minute=avg_minute, 
        id='daily_reminder'
    )

def check_daily_record():
    try:
        spreadsheet_id = os.environ.get("SPREADSHEET_ID")
        if not spreadsheet_id:
            return
            
        stats = google_services.get_study_stats(spreadsheet_id)
        today_minutes = stats.get("today_minutes", 0)
        
        if today_minutes == 0:
            notification.notify(
                title='AIコーチからのリマインド',
                message='本日の学習記録がまだありません！少しでも進めて記録をつけましょう。',
                app_name='AiCoaching',
                timeout=10
            )
            print("Reminder notification sent.")
        else:
            print(f"Daily record exists ({today_minutes} mins). No reminder needed.")
            
        # 次回分のスケジュールを再計算・セット
        schedule_next_reminder()
        
    except Exception as e:
        print(f"Scheduler error: {e}")

def start():
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
        # 起動時に最初のスケジュールを計算してセット
        schedule_next_reminder()
