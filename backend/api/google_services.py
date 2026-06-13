import os
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build

# credentials.json のパスを解決
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")

# スコープの設定（スプレッドシートとカレンダーの両方の読み書き権限）
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/calendar.events'
]

def get_credentials():
    return service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=SCOPES
    )

def get_gspread_client():
    creds = get_credentials()
    return gspread.authorize(creds)

def get_calendar_service():
    creds = get_credentials()
    return build('calendar', 'v3', credentials=creds)

# ==========================================
# Spreadsheet Helper Functions
# ==========================================

def append_daily_record(spreadsheet_id, date, target, content, study_time, progress, rating, comment):
    """
    日々の記録シートの末尾に記録と評価を追記する
    """
    client = get_gspread_client()
    sheet = client.open_by_key(spreadsheet_id).worksheet("日々の記録履歴")
    
    # 追記するデータの配列: ['日付', '目標資格', '今日やったこと', '学習時間', '進捗', '評価', 'コメント']
    row_data = [date, target, content, f"{study_time}分", progress, rating, comment]
    
    # A列から追記
    sheet.append_row(row_data)

def append_quiz_record(spreadsheet_id, date, glossary, question, user_answer, correct_answer, is_correct, next_review_date, quiz_format="選択式", target=""):
    """
    小テストの履歴をシートに記録する
    """
    client = get_gspread_client()
    sheet = client.open_by_key(spreadsheet_id).worksheet("小テスト履歴")
    row_data = [date, glossary, question, user_answer, correct_answer, is_correct, next_review_date, quiz_format, target]
    sheet.append_row(row_data)

def get_past_subjects(spreadsheet_id):
    """
    日々の記録履歴と学習カレンダーから過去の目標資格・学習テーマ（重複なし）を取得してリストで返す
    """
    try:
        client = get_gspread_client()
        sh = client.open_by_key(spreadsheet_id)
        subjects = set()
        
        # 1. 日々の記録履歴から取得
        try:
            sheet_daily = sh.worksheet("日々の記録履歴")
            col_daily = sheet_daily.col_values(2)
            for val in col_daily[1:]:
                if val.strip():
                    subjects.add(val.strip())
        except Exception:
            pass
            
        # 2. 学習カレンダーから推奨学習テーマを取得
        try:
            sheet_cal = sh.worksheet("学習カレンダー")
            col_cal = sheet_cal.col_values(2)
            for val in col_cal[1:]:
                if val.strip():
                    subjects.add(val.strip())
        except Exception:
            pass
            
        return list(subjects)
    except Exception as e:
        print(f"Failed to fetch past subjects: {e}")
        return []

def get_past_contents(spreadsheet_id):
    """
    日々の記録履歴から過去の「今日やったこと」を取得してリストで返す
    """
    try:
        client = get_gspread_client()
        sh = client.open_by_key(spreadsheet_id)
        contents = set()
        try:
            sheet_daily = sh.worksheet("日々の記録履歴")
            col_daily = sheet_daily.col_values(3) # C列: 今日やったこと
            for val in col_daily[1:]:
                if val.strip():
                    contents.add(val.strip())
        except Exception:
            pass
        return list(contents)
    except Exception as e:
        print(f"Failed to fetch roadmap: {e}")
        return []

def append_consultation(spreadsheet_id, target, user_query, ai_response):
    """
    学習相談の履歴をシートに記録する
    シート名: 学習相談履歴
    カラム: A. 日時, B. 目標資格, C. ユーザーの相談内容, D. AIの回答
    """
    try:
        client = get_gspread_client()
        sh = client.open_by_key(spreadsheet_id)
        try:
            worksheet = sh.worksheet("学習相談履歴")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title="学習相談履歴", rows="1000", cols="10")
            worksheet.append_row(["日時", "目標資格", "相談内容", "AIの回答"])
        
        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worksheet.append_row([now_str, target, user_query, ai_response])
        print(f"Consultation saved to sheet: {target}")
    except Exception as e:
        print(f"Failed to append consultation: {e}")

def get_past_consultations(spreadsheet_id, target):
    """
    目標資格に関連する過去の学習相談履歴を取得する
    """
    try:
        client = get_gspread_client()
        sh = client.open_by_key(spreadsheet_id)
        try:
            worksheet = sh.worksheet("学習相談履歴")
        except gspread.exceptions.WorksheetNotFound:
            return []
            
        records = worksheet.get_all_records()
        past_consultations = []
        for r in records:
            if str(r.get("目標資格", "")) == str(target):
                past_consultations.append({
                    "date": r.get("日時", ""),
                    "query": r.get("相談内容", ""),
                    "response": r.get("AIの回答", "")
                })
        return past_consultations
    except Exception as e:
        print(f"Failed to fetch past consultations: {e}")
        return []

def get_total_study_time(spreadsheet_id, target):
    """
    指定した目標資格に対する合計学習時間をポモドーロ履歴から集計して返す（分単位）
    """
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(spreadsheet_id).worksheet("ポモドーロ履歴")
        records = sheet.get_all_values()
        total_minutes = 0
        # ヘッダーを除外
        for row in records[1:]:
            if len(row) >= 3 and row[1].strip() == target:
                time_str = row[2].replace("分", "").strip()
                if time_str.isdigit():
                    total_minutes += int(time_str)
        return total_minutes
    except Exception as e:
        print(f"Failed to calculate total study time: {e}")
        return 0

def get_study_stats(spreadsheet_id):
    """
    本日の合計学習時間、ストリーク、ヒートマップデータを取得する
    """
    try:
        import datetime
        client = get_gspread_client()
        sh = client.open_by_key(spreadsheet_id)
        
        # 本日の合計学習時間 (ポモドーロ履歴から)
        today = datetime.date.today().isoformat()
        pomo_sheet = sh.worksheet("ポモドーロ履歴")
        pomo_records = pomo_sheet.get_all_values()
        today_minutes = 0
        for row in pomo_records[1:]:
            if len(row) >= 3 and row[0].startswith(today):
                time_str = row[2].replace("分", "").strip()
                if time_str.isdigit():
                    today_minutes += int(time_str)
                    
        # 日々の記録からストリークとヒートマップを集計
        daily_sheet = sh.worksheet("日々の記録履歴")
        daily_records = daily_sheet.get_all_values()
        
        # study_dates = { "YYYY-MM-DD": total_minutes }
        study_dates = {}
        for row in daily_records[1:]:
            if len(row) >= 4:
                date_str = row[0][:10]
                time_str = row[3].replace("分", "").strip()
                mins = int(time_str) if time_str.isdigit() else 0
                study_dates[date_str] = study_dates.get(date_str, 0) + mins
                
        # ストリーク計算
        streak = 0
        current_date = datetime.date.today()
        # もし今日やってなくても、昨日から繋がっていればストリーク継続とするため昨日もチェック
        if current_date.isoformat() not in study_dates:
            current_date -= datetime.timedelta(days=1)
            
        while current_date.isoformat() in study_dates:
            streak += 1
            current_date -= datetime.timedelta(days=1)
            
        return {
            "today_minutes": today_minutes,
            "streak": streak,
            "heatmap": study_dates
        }
    except Exception as e:
        print("get_study_stats error:", e)
        return {"today_minutes": 0, "streak": 0, "heatmap": {}}

def get_weakness_questions(spreadsheet_id, target):
    """
    小テスト履歴から、指定した目標資格で「不正解」だった問題のリストを取得する
    """
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(spreadsheet_id).worksheet("小テスト履歴")
        records = sheet.get_all_values()
        weaknesses = []
        for row in records[1:]:
            # I列(Index 8)が目標資格、F列(Index 5)が判定、C列(Index 2)が出題内容
            if len(row) >= 9 and row[8].strip() == target.strip():
                if "不正解" in row[5] or "部分点" in row[5]:
                    weaknesses.append({
                        "glossary": row[1],
                        "question": row[2]
                    })
        return weaknesses
    except Exception as e:
        print("get_weakness_questions error:", e)
        return []

def append_pomodoro_record(spreadsheet_id, date_time, subject, duration_minutes):
    """
    ポモドーロの個別セッション記録を保存する
    """
    client = get_gspread_client()
    sheet = client.open_by_key(spreadsheet_id).worksheet("ポモドーロ履歴")
    row_data = [date_time, subject, f"{duration_minutes}分"]
    sheet.append_row(row_data)

def write_roadmap(spreadsheet_id, target, milestones):
    """
    生成されたロードマップを学習カレンダーシートに保存する
    ※既存の同目標資格のデータがある場合は削除して上書きし、他の資格データは残す
    """
    client = get_gspread_client()
    sh = client.open_by_key(spreadsheet_id)
    
    try:
        worksheet = sh.worksheet("学習カレンダー")
    except gspread.WorksheetNotFound:
        worksheet = sh.add_worksheet(title="学習カレンダー", rows="100", cols="10")
        
    records = worksheet.get_all_values()
    headers = ["目標資格", "週", "推奨学習テーマ", "目標進捗率", "推奨学習時間", "実績（完了日）"]
    
    if not records:
        filtered_records = [headers]
    else:
        filtered_records = [records[0]] + [row for row in records[1:] if len(row) > 0 and row[0].strip() != target.strip()]
        
    for item in milestones:
        filtered_records.append([
            target,
            f"第{item.get('week')}週",
            item.get('topic'),
            f"{item.get('target_progress_percent')}%",
            f"平日:{item.get('weekday_minutes', 60)}分/休日:{item.get('weekend_minutes', 120)}分",
            ""
        ])
    
    worksheet.clear()
    worksheet.update('A1', filtered_records)

def get_roadmap(spreadsheet_id, target):
    """
    目標資格に一致するロードマップを取得する
    """
    client = get_gspread_client()
    sh = client.open_by_key(spreadsheet_id)
    try:
        worksheet = sh.worksheet("学習カレンダー")
        records = worksheet.get_all_values()
        milestones = []
        for row in records[1:]:
            if len(row) >= 5 and row[0].strip() == target.strip():
                milestones.append({
                    "week": row[1].replace("第", "").replace("週", ""),
                    "topic": row[2],
                    "target_progress_percent": row[3].replace("%", ""),
                    "recommended_hours": row[4].replace("時間", "")
                })
        return milestones
    except Exception as e:
        print("get_roadmap error:", e)
        return []

# ==========================================
# Calendar Helper Functions
# ==========================================

def insert_calendar_events(calendar_id, milestones, qualification):
    """
    週ごとのマイルストーンをGoogleカレンダーの「終日予定」として毎日登録する。
    重複を防ぐため、事前に同じ目標資格の予定を削除する。
    """
    service = get_calendar_service()
    
    # 1. 既存の予定を削除 (privateExtendedPropertyで識別)
    page_token = None
    while True:
        try:
            events = service.events().list(
                calendarId=calendar_id,
                privateExtendedProperty=f"ai_coaching_app_target={qualification}",
                pageToken=page_token
            ).execute()
            for event in events.get('items', []):
                try:
                    service.events().delete(calendarId=calendar_id, eventId=event['id']).execute()
                except Exception as e:
                    print("Failed to delete event", e)
            page_token = events.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            print("Failed to fetch existing events", e)
            break

    # 2. 新しい予定を追加
    import datetime
    current_date = datetime.date.today()
    
    for m in milestones:
        weekday_mins = m.get("weekday_minutes", 60)
        weekend_mins = m.get("weekend_minutes", 120)
        topic = m.get("topic", "学習")
        
        for _ in range(7):
            is_weekend = current_date.weekday() >= 5
            mins = weekend_mins if is_weekend else weekday_mins
            
            event = {
                'summary': f'[AIコーチ] {qualification} ({mins}分)',
                'description': f"今週のテーマ: {topic}\n{m.get('description', '')}",
                'start': {
                    'date': current_date.isoformat(),
                },
                'end': {
                    'date': (current_date + datetime.timedelta(days=1)).isoformat(),
                },
                'extendedProperties': {
                    'private': {
                        'ai_coaching_app_target': qualification
                    }
                }
            }
            try:
                service.events().insert(calendarId=calendar_id, body=event).execute()
            except Exception as e:
                print("Failed to insert event", e)
                
            current_date += datetime.timedelta(days=1)
