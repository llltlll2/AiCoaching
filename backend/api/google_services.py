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

def append_daily_record(spreadsheet_id, date, target, content, study_time, progress, rating, comment, category="学習"):
    """
    日々の記録シートの末尾に記録と評価を追記する
    """
    client = get_gspread_client()
    sheet = client.open_by_key(spreadsheet_id).worksheet("日々の記録履歴")
    
    # 追記するデータの配列: ['日付', 'タスク/目標名', '今日やったこと', '作業時間', '進捗', '評価', 'コメント', 'カテゴリ']
    row_data = [date, target, content, f"{study_time}分", progress, rating, comment, category]
    
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
        
        # 1. 学習予定資格から取得 (新仕様: 親オブジェクト)
        try:
            sheet_plan = sh.worksheet("学習予定資格")
            col_plan = sheet_plan.col_values(1)
            for val in col_plan[1:]:
                if val.strip():
                    subjects.add(val.strip())
        except Exception:
            pass
            
        # 2. 互換性のため過去の日々の記録履歴からも取得
        try:
            sheet_daily = sh.worksheet("日々の記録履歴")
            col_daily = sheet_daily.col_values(2)
            for val in col_daily[1:]:
                if val.strip():
                    subjects.add(val.strip())
        except Exception:
            pass
            
        return list(subjects)
    except Exception as e:
        print(f"Failed to fetch past subjects: {e}")
        return []

def get_personalities(spreadsheet_id):
    """
    AIコーチ設定シートから性格のリストを取得する
    """
    default_prompt = (
        "あなたは「Limbus Company」に登場する天才科学者「ファウスト」です。\n"
        "学習者（二人称はアナタ、もしくは管理人）に対して、非常に理性的、冷静かつ客観的、そして知的で少し誇り高い態度で接してください。\n"
        "【特徴的な話し方】\n"
        "1. 自分のことを「ファウストは〜」「ファウストが〜」と三人称で呼びます。「私」や「自分」は絶対に使いません。\n"
        "2. 感情の起伏がほとんどなく、常に淡々と話します。丁寧語（〜です、〜ます、〜でしょう）を基本とします。\n"
        "3. 「ファウストはすべてを知っています」「それはファウストが設計したからです」「なぜならファウストは天才だからです」といった、絶対的な知性に対する自信に満ちたセリフを自然に混ぜてください。\n"
        "4. 学習者の進捗に対して大げさに驚いたり感情的に褒めたりせず、「ファウストの予想通りですね」「当然の結果です」「ファウストの計算に狂いはありません」のように、淡々と肯定してください。\n"
        "5. つまずきに対しては、「ファウストが解説しましょう」と、論理的でスマートな解説を行ってください。"
    )
    fallback_personalities = [
        {"name": "デフォルト（ファウスト）", "prompt": default_prompt, "voice_id": 47}, 
        {"name": "厳格なスパルタコーチ", "prompt": "あなたは学習者を厳しく鍛え上げるスパルタコーチです。一切の甘えを許さず、厳しい言葉でモチベーションを煽ります。敬語は使いません。", "voice_id": 11},
        {"name": "優しいお姉さん", "prompt": "あなたは学習者を優しく包み込むお姉さんです。「〜だね」「〜してね」といった柔らかい口調で、学習者を常に褒めて励まします。", "voice_id": 8}
    ]

    if not spreadsheet_id:
        return fallback_personalities

    try:
        client = get_gspread_client()
        sh = client.open_by_key(spreadsheet_id)
        try:
            sheet = sh.worksheet("AIコーチ設定")
        except gspread.exceptions.WorksheetNotFound:
            sheet = sh.add_worksheet(title="AIコーチ設定", rows="100", cols="5")
            sheet.append_row(["性格名", "プロンプト", "デフォルト音声ID"])
            sheet.append_row(["デフォルト（ファウスト）", default_prompt, 47])
            sheet.append_row(["厳格なスパルタコーチ", fallback_personalities[1]["prompt"], 11])
            sheet.append_row(["優しいお姉さん", fallback_personalities[2]["prompt"], 8])
            return fallback_personalities
            
        records = sheet.get_all_records()
        personalities = []
        for r in records:
            if str(r.get("性格名", "")).strip():
                personalities.append({
                    "name": str(r.get("性格名", "")).strip(),
                    "prompt": str(r.get("プロンプト", "")).strip(),
                    "voice_id": str(r.get("デフォルト音声ID", "")).strip() or "47"
                })
        return personalities if personalities else fallback_personalities
    except Exception as e:
        print(f"Failed to fetch personalities: {e}")
        return fallback_personalities

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

def get_average_study_time(spreadsheet_id):
    """
    ポモドーロ履歴から過去の学習完了時間の平均を算出し、(hour, minute) のタプルで返す。
    深夜0時〜4時は24時〜28時として計算する。
    データがない場合はデフォルトとして (20, 0) を返す。
    """
    try:
        client = get_gspread_client()
        sh = client.open_by_key(spreadsheet_id)
        try:
            worksheet = sh.worksheet("ポモドーロ履歴")
        except gspread.WorksheetNotFound:
            return (20, 0)
            
        records = worksheet.get_all_records()
        if not records:
            return (20, 0)
            
        total_minutes = 0
        count = 0
        import datetime
        
        for row in records:
            dt_str = str(row.get("完了日時", ""))
            try:
                # 期待フォーマット: YYYY-MM-DD HH:MM:SS
                dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                hour = dt.hour
                minute = dt.minute
                
                # 深夜0〜4時は24〜28時として扱う
                if hour < 4:
                    hour += 24
                    
                total_minutes += (hour * 60) + minute
                count += 1
            except ValueError:
                continue
                
        if count == 0:
            return (20, 0)
            
        avg_minutes = total_minutes // count
        avg_hour = avg_minutes // 60
        avg_minute = avg_minutes % 60
        
        # 24以上の場合は0-23の範囲に戻す
        if avg_hour >= 24:
            avg_hour -= 24
            
        return (avg_hour, avg_minute)
    except Exception as e:
        print(f"Failed to calculate average study time: {e}")
        return (20, 0)

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
        # category_data = { "YYYY-MM-DD": { "学習": 30, "仕事": 60 } }
        study_dates = {}
        category_data = {}
        for row in daily_records[1:]:
            if len(row) >= 4:
                date_str = row[0][:10]
                time_str = row[3].replace("分", "").strip()
                mins = int(time_str) if time_str.isdigit() else 0
                cat = row[7] if len(row) > 7 else "学習"
                
                study_dates[date_str] = study_dates.get(date_str, 0) + mins
                
                if date_str not in category_data:
                    category_data[date_str] = {}
                category_data[date_str][cat] = category_data[date_str].get(cat, 0) + mins
                
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
            "heatmap": study_dates,
            "category_data": category_data
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

def append_pomodoro_record(spreadsheet_id, date_time, subject, duration_minutes, category="学習"):
    """
    ポモドーロの個別セッション記録を保存する
    """
    client = get_gspread_client()
    sheet = client.open_by_key(spreadsheet_id).worksheet("ポモドーロ履歴")
    row_data = [date_time, subject, f"{duration_minutes}分", category]
    sheet.append_row(row_data)

def write_roadmap(spreadsheet_id, target, milestones):
    """
    生成されたロードマップを「学習予定資格」および「学習カレンダー」シートに保存する
    """
    client = get_gspread_client()
    sh = client.open_by_key(spreadsheet_id)
    import datetime
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 学習予定資格（親）に登録
    try:
        plan_sheet = sh.worksheet("学習予定資格")
    except gspread.WorksheetNotFound:
        plan_sheet = sh.add_worksheet(title="学習予定資格", rows="100", cols="5")
        plan_sheet.append_row(["目標資格", "登録日時"])
        
    try:
        plan_records = plan_sheet.col_values(1)
        if target not in plan_records:
            plan_sheet.append_row([target, now_str])
    except Exception as e:
        print("Failed to update 学習予定資格:", e)
    
    # 2. 学習カレンダー（子）に週ごとの詳細を登録
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
