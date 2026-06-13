from apscheduler.schedulers.background import BackgroundScheduler
import os
import datetime
from plyer import notification
from api import google_services

def check_daily_record():
    try:
        # Check if there's any record for today
        spreadsheet_id = os.environ.get("SPREADSHEET_ID")
        if not spreadsheet_id:
            return
            
        stats = google_services.get_study_stats(spreadsheet_id)
        today_minutes = stats.get("today_minutes", 0)
        
        if today_minutes == 0:
            # 記録がない場合、トースト通知を表示
            notification.notify(
                title='AIコーチからのリマインド',
                message='本日の学習記録がまだありません！少しでも進めて記録をつけましょう。',
                app_name='AiCoaching',
                timeout=10
            )
            print("Reminder notification sent.")
        else:
            print(f"Daily record exists ({today_minutes} mins). No reminder needed.")
    except Exception as e:
        print(f"Scheduler error: {e}")

def start():
    scheduler = BackgroundScheduler()
    # 毎日20:00に実行
    scheduler.add_job(check_daily_record, 'cron', hour=20, minute=0)
    scheduler.start()
