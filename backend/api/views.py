from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from google import genai
from google.genai import types
import requests
import json
import os
import time
import re
from api import google_services

UPLOADED_FILES_CACHE = {}

def extract_json(text):
    text = text.strip()
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    return json.loads(text)

def get_or_upload_materials(client):
    global UPLOADED_FILES_CACHE
    materials_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "materials")
    if not os.path.exists(materials_dir):
        os.makedirs(materials_dir, exist_ok=True)
        return []
        
    local_files = [f for f in os.listdir(materials_dir) if f.endswith('.pdf') or f.endswith('.txt')]
    if not local_files:
        return []
        
    try:
        remote_files = {f.display_name: f for f in client.files.list()}
    except Exception:
        remote_files = {}
        
    uploaded_files = []
    
    for filename in local_files:
        file_path = os.path.join(materials_dir, filename)
        if filename in UPLOADED_FILES_CACHE:
            uploaded_files.append(UPLOADED_FILES_CACHE[filename])
        elif filename in remote_files:
            f = remote_files[filename]
            UPLOADED_FILES_CACHE[filename] = f
            uploaded_files.append(f)
        else:
            try:
                f = client.files.upload(file=file_path, config={'display_name': filename})
                UPLOADED_FILES_CACHE[filename] = f
                uploaded_files.append(f)
            except Exception as e:
                print(f"Upload error for {filename}: {e}")
                
    for i, f in enumerate(uploaded_files):
        while getattr(f, 'state', None) in ("PROCESSING", "STATE_PROCESSING"):
            time.sleep(2)
            f = client.files.get(name=f.name)
            UPLOADED_FILES_CACHE[f.display_name] = f
            uploaded_files[i] = f
            
    return uploaded_files

from django.shortcuts import render

def frontend_view(request):
    return render(request, 'index.html')

# VOICEVOX APIの基本URL (ローカル環境想定)
VOICEVOX_URL = "http://localhost:50021"

@csrf_exempt
def study_coaching_hub(request):
    if request.method != 'POST':
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
    
    # Gemini APIの初期化 (環境変数がロードされた後に呼び出すためここに配置するか、settings.pyロード済み前提でトップでもOK)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return JsonResponse({"status": "error", "message": "API key not found"}, status=500)
    client = genai.Client(api_key=api_key)

    try:
        # 1. GASからの共通構造化データのパース
        payload = json.loads(request.body)
        phase = payload.get("phase")
        
        # ----------------------------------------------------------------
        # フェーズ①：初期設定草案作成（カレンダー・シート保存なし）
        # ----------------------------------------------------------------
        if phase == "draft_roadmap":
            qualification = payload.get("qualification")
            duration_months = payload.get("duration_months")
            syllabus = payload.get("syllabus", "")
            constraints = payload.get("constraints", "")
            
            system_instruction = (
                "あなたは優秀な学習コンサルタントです。指定された資格と期間、シラバス情報、およびユーザーからの相談・制約条件に基づき、"
                "週ごとの学習計画と、その週の平日・休日の推奨学習時間(分)を以下のJSONフォーマットで作成してください。\n"
                "出力例: {\"milestones\": [{\"week\": 1, \"topic\": \"テーマ名\", \"target_progress_percent\": 10, \"weekday_minutes\": 60, \"weekend_minutes\": 180, \"description\": \"詳細\"}]}\n"
                "必ず有効なJSONのみを出力してください。Markdownブロックは不要です。"
            )
            
            prompt = f"資格名: {qualification}, 期間: {duration_months}ヶ月"
            if syllabus:
                prompt += f"\nシラバス・参考情報: {syllabus}"
            if constraints:
                prompt += f"\nユーザーからの相談・制約: {constraints}"
                
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction
                )
            )
            
            result_plan = extract_json(response.text)
            return JsonResponse({"status": "success", "plan": result_plan})

        elif phase == 'get_consultations':
            target = payload.get('qualification')
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            if not target or not spreadsheet_id:
                return JsonResponse({'status': 'error', 'message': 'Qualification and Spreadsheet ID are required'})
            history = google_services.get_past_consultations(spreadsheet_id, target)
            return JsonResponse({'status': 'success', 'history': history})
            
        # ----------------------------------------------------------------
        # フェーズ①-2：学習計画の確定と同期（シート・カレンダー保存）
        # ----------------------------------------------------------------
        elif phase == "sync_roadmap":
            qualification = payload.get("qualification")
            milestones = payload.get("milestones", [])
            
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            calendar_id = os.environ.get("CALENDAR_ID")
            if spreadsheet_id:
                try:
                    google_services.write_roadmap(spreadsheet_id, qualification, milestones)
                except Exception as e:
                    print("Roadmap save error:", e)
                    
            if calendar_id:
                try:
                    google_services.insert_calendar_events(calendar_id, milestones, qualification)
                except Exception as e:
                    print("Calendar sync error:", e)

            return JsonResponse({"status": "success"})
            
        # ----------------------------------------------------------------
        # フェーズ①-3：学習計画についての相談 (Memory + Feedback)
        # ----------------------------------------------------------------
        elif phase == "consult_plan":
            qualification = payload.get("qualification")
            query = payload.get("query")
            speaker_id = payload.get("speaker_id", 47)
            
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            past_consultations = []
            roadmap = []
            
            if spreadsheet_id:
                past_consultations = google_services.get_past_consultations(spreadsheet_id, qualification)
                roadmap = google_services.get_roadmap(spreadsheet_id, qualification)
                
            # プロンプトの構築
            history_text = "\n".join([f"過去の相談({c['date']}): {c['query']}\nAI回答: {c['response']}" for c in past_consultations[-5:]])
            roadmap_text = "\n".join([f"第{r['week']}週: {r['topic']} (目標: {r['target_progress_percent']}%, {r['recommended_hours']})" for r in roadmap])
            
            base_prompt = payload.get("system_prompt", "あなたは優秀な学習コンサルタントです。ユーザーからの学習計画に関する相談に乗ります。必要であれば過去の相談履歴や現在のロードマップを踏まえて、具体的な日程調整や学習方法のフィードバックを行ってください。")
            system_instruction = base_prompt + (
                "\n\n必ず以下のJSON構造のみを出力してください。\n"
                "{\n"
                "  \"advice\": \"ユーザーへのアドバイスやフィードバック本文\"\n"
                "}"
            )
            
            prompt = f"目標資格: {qualification}\n\n【現在のロードマップ】\n{roadmap_text}\n\n【過去の相談履歴】\n{history_text}\n\n【今回の相談内容】\n{query}"
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system_instruction)
            )
            
            result_json = extract_json(response.text)
            advice = result_json.get("advice", "アドバイスを生成できませんでした。")
            
            # シートに保存
            if spreadsheet_id:
                google_services.append_consultation(spreadsheet_id, qualification, query, advice)
                
            # VOICEVOX再生
            if advice:
                trigger_voicevox(advice, speaker_id)
                
            return JsonResponse({"status": "success", "advice": advice})
            
        # ----------------------------------------------------------------
        # フェーズ②：日々の運用（コーチング＆音声化）
        # ----------------------------------------------------------------
        elif phase == "daily_report":
            target = payload.get("target")
            content = payload.get("content")
            progress = payload.get("progress_volume")
            memo = payload.get("memo", "")
            category = payload.get("category", "学習")
            
            base_prompt = payload.get("system_prompt", "あなたは優秀な学習伴走コーチです。すぐ正解を教えず、自発的な気づきを促す段階的なヒントや問いかけを行ってください。")
            
            if category != "学習":
                system_instruction = base_prompt + (
                    f"\n\n今回の対象は「学習」ではなく、ユーザーの「{category}」カテゴリのタスクに関する日報です。"
                    "勉強のコーチではなく、タスクや生産性向上のコーチとして、アドバイスや共感の言葉を含めてください。"
                    "出力は必ず以下のJSON構造を厳守してください。Markdownブロックは不要です。\n"
                    "出力例: {\"daily_rating\": \"B\", \"progress_status\": \"delayed_light\", \"coaching_comment\": \"フィードバック本文...\"}"
                )
            else:
                system_instruction = base_prompt + (
                    "\n\nもしユーザーからの『学習メモ・悩み』がある場合は、それに対するアドバイスや共感の言葉も含めてください。"
                    "出力は必ず以下のJSON構造を厳守してください。Markdownブロックは不要です。\n"
                    "出力例: {\"daily_rating\": \"B\", \"progress_status\": \"delayed_light\", \"coaching_comment\": \"フィードバック本文...\"}"
                )
            
            # File APIを利用して教材を読み込み
            materials = get_or_upload_materials(client)
            
            prompt = f"目標資格：{target}, 本日実施した内容：{content}, 進捗：{progress}"
            if memo:
                prompt += f"\n学習メモ・悩み：{memo}"
            contents = materials + [prompt]
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=[{"google_search": {}}]
                )
            )
            result_json = extract_json(response.text)
            
            # Spreadsheet Sync
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            study_time = payload.get("study_time", 0)
            if spreadsheet_id:
                try:
                    google_services.append_daily_record(
                        spreadsheet_id=spreadsheet_id,
                        date=payload.get("date", "Today"),
                        target=target,
                        content=content,
                        study_time=study_time,
                        progress=progress,
                        rating=result_json.get("daily_rating", ""),
                        comment=result_json.get("coaching_comment", ""),
                        category=category
                    )
                except Exception as e:
                    print("Spreadsheet append error:", e)
            
            # VOICEVOXへのブリッジ処理
            speaker_id = payload.get("speaker_id", 47)
            coaching_text = result_json.get("coaching_comment", "")
            if coaching_text:
                trigger_voicevox(coaching_text, speaker_id)
                
            return JsonResponse({
                "status": "success",
                "evaluation": result_json
            })
            
        # ----------------------------------------------------------------
        # フェーズ③：小テスト＆用語集の生成 (NotebookLM風)
        # ----------------------------------------------------------------
        elif phase == "generate_quiz":
            target = payload.get("target", "現在の学習テーマ")
            quiz_format = payload.get("quiz_format", "記述式")
            weakness_mode = payload.get("weakness_mode", False)
            
            if weakness_mode:
                spreadsheet_id = os.environ.get("SPREADSHEET_ID")
                weaknesses = google_services.get_weakness_questions(spreadsheet_id, target) if spreadsheet_id else []
                if not weaknesses:
                    return JsonResponse({"status": "error", "message": "弱点データが見つかりませんでした。通常の小テストを実施してください。"})
                # 弱点からランダムに1問選ぶなど（ここではプロンプトに弱点リストを含めて再構成させる）
                weakness_text = "\n".join([f"Q: {w['question']}" for w in weaknesses[:3]])
                base_prompt = payload.get("system_prompt", "あなたは優秀な学習チューターです。")
                system_instruction = base_prompt + (
                    "\n\n以下の過去に間違えた問題（弱点）をベースに、似たような問題を再出題してください。"
                    "必ず以下のJSON構造のみを出力してください。Markdownブロックは不要です。\n"
                    "{\n"
                    "  \"glossary\": [{\"term\": \"弱点用語1\", \"definition\": \"解説1\"}],\n"
                    f"  \"question\": \"{quiz_format}で問題を1問出題してください。\"\n"
                    "}"
                )
                prompt = f"目標資格: {target}\n過去の弱点問題リスト:\n{weakness_text}"
                contents = [prompt]
            else:
                base_prompt = payload.get("system_prompt", "あなたは優秀な学習チューターです。")
                system_instruction = base_prompt + (
                    "\n\n提供された資料や最新情報に基づき、学習者が理解を深めるためのコンテンツを作成します。"
                    "必ず以下のJSON構造のみを出力してください。Markdownブロックは不要です。\n"
                    "{\n"
                    "  \"glossary\": [{\"term\": \"用語1\", \"definition\": \"解説1\"}, ...],\n"
                    f"  \"question\": \"学習資料に基づく{quiz_format}の問題を1問出題してください。\"\n"
                    "}"
                )
                materials = get_or_upload_materials(client)
                prompt = f"「{target}」に関する重要な専門用語を3〜5個抽出し、用語集を作成した上で、理解度を測るための{quiz_format}の問題を1問出題してください。"
                contents = materials + [prompt]
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=[{"google_search": {}}]
                )
            )
            return JsonResponse({"status": "success", "quiz_data": extract_json(response.text)})

        elif phase == "quiz_chat":
            query = payload.get("query", "")
            base_prompt = payload.get("system_prompt", "あなたは熱心なAIコーチです。")
            
            # 簡易的に文脈なしで答えるか、あるいは前のクイズ結果を持たせることは今回は省略（本来はセッション等で持つが簡易化）
            system_instruction = base_prompt + (
                "\n\n学習者が直前に解いた小テストについて、追加の質問や解説を求めています。\n"
                "丁寧かつ分かりやすく答えてください。\n"
            )
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=query,
                config=types.GenerateContentConfig(system_instruction=system_instruction)
            )
            reply = response.text
            
            speaker_id = payload.get("speaker_id", 47)
            if reply:
                trigger_voicevox(reply, speaker_id)
                
            return JsonResponse({"status": "success", "response": reply})

        # ----------------------------------------------------------------
        # フェーズ④：小テストの採点と保存
        # ----------------------------------------------------------------
        elif phase == "evaluate_quiz":
            question = payload.get("question")
            user_answer = payload.get("user_answer")
            glossary = payload.get("glossary_text", "")
            
            base_prompt = payload.get("system_prompt", "あなたは厳密な採点官です。")
            system_instruction = base_prompt + (
                "\n\n問題に対する学習者の回答を評価してください。"
                "必ず以下のJSON構造のみを出力してください。\n"
                "{\n"
                "  \"correct_answer\": \"模範解答と解説\",\n"
                "  \"is_correct\": \"正解\" または \"不正解\" または \"部分点\",\n"
                "  \"feedback\": \"学習者へのフィードバック\"\n"
                "}"
            )
            
            prompt = f"問題: {question}\n学習者の回答: {user_answer}\n厳密に採点・解説してください。"
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system_instruction)
            )
            eval_result = extract_json(response.text)
            
            # Spreadsheet Sync
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            if spreadsheet_id:
                try:
                    import datetime
                    today = datetime.date.today().isoformat()
                    # 簡易的な忘却曲線計算（不正解なら明日、正解なら3日後）
                    is_correct = eval_result.get("is_correct", "")
                    days_to_add = 1 if "不正解" in is_correct else 3
                    next_review = (datetime.date.today() + datetime.timedelta(days=days_to_add)).isoformat()
                    
                    google_services.append_quiz_record(
                        spreadsheet_id=spreadsheet_id,
                        date=today,
                        glossary=glossary,
                        question=question,
                        user_answer=user_answer,
                        correct_answer=eval_result.get("correct_answer", ""),
                        is_correct=is_correct,
                        next_review_date=next_review,
                        quiz_format=payload.get("quiz_format", "選択式"),
                        target=payload.get("target", "")
                    )
                except Exception as e:
                    print("Quiz save error:", e)
                    
            speaker_id = payload.get("speaker_id", 47)
            if eval_result.get("feedback"):
                trigger_voicevox(eval_result.get("feedback"), speaker_id)
                
            return JsonResponse({"status": "success", "evaluation": eval_result})

        elif phase == 'daily_report_chat':
            query = payload.get("query", "")
            base_prompt = payload.get("system_prompt", "あなたは熱心なAIコーチです。")
            
            system_instruction = base_prompt + (
                "\n\n学習者が日報のフィードバックに対して追加の質問をしてきました。\n"
                "簡潔で励みになるように、分かりやすく答えてください。\n"
            )
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=query,
                config=types.GenerateContentConfig(system_instruction=system_instruction)
            )
            reply = response.text
            
            speaker_id = payload.get("speaker_id", 47)
            if reply:
                trigger_voicevox(reply, speaker_id)
                
            return JsonResponse({"status": "success", "response": reply})

        # ----------------------------------------------------------------
        # フェーズ⑤：過去の学習テーマ取得 (Autocomplete用)
        # ----------------------------------------------------------------
        elif phase == "get_past_subjects":
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            subjects = []
            if spreadsheet_id:
                subjects = google_services.get_past_subjects(spreadsheet_id)
            return JsonResponse({"status": "success", "subjects": subjects})

        # ----------------------------------------------------------------
        # フェーズ⑤-2：過去の「今日やったこと」取得 (Autocomplete用)
        # ----------------------------------------------------------------
        elif phase == "get_past_contents":
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            contents = []
            if spreadsheet_id:
                contents = google_services.get_past_contents(spreadsheet_id)
            return JsonResponse({"status": "success", "contents": contents})

        # ----------------------------------------------------------------
        # フェーズ⑥：ポモドーロの個別記録
        # ----------------------------------------------------------------
        elif phase == "save_pomodoro":
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            if spreadsheet_id:
                try:
                    import datetime
                    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    google_services.append_pomodoro_record(
                        spreadsheet_id=spreadsheet_id,
                        date_time=now_str,
                        subject=payload.get("target", "無題"),
                        duration_minutes=payload.get("duration", 0),
                        category=payload.get("category", "学習")
                    )
                except Exception as e:
                    print("Pomodoro save error:", e)
            return JsonResponse({"status": "success"})

        # ----------------------------------------------------------------
        # フェーズ⑦：目標資格ごとの合計学習時間取得
        # ----------------------------------------------------------------
        elif phase == "get_total_study_time":
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            target = payload.get("target")
            total_time = 0
            if spreadsheet_id and target:
                total_time = google_services.get_total_study_time(spreadsheet_id, target)
            return JsonResponse({"status": "success", "total_minutes": total_time})

        # ----------------------------------------------------------------
        # フェーズ⑧：既存のロードマップ取得
        # ----------------------------------------------------------------
        elif phase == "get_roadmap":
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            target = payload.get("target")
            milestones = []
            if spreadsheet_id and target:
                milestones = google_services.get_roadmap(spreadsheet_id, target)
            return JsonResponse({"status": "success", "milestones": milestones})

        # ----------------------------------------------------------------
        # フェーズ⑨：ダッシュボード用統計データ取得
        # ----------------------------------------------------------------
        elif phase == "get_study_stats":
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            stats = {"today_minutes": 0, "streak": 0, "heatmap": {}}
            if spreadsheet_id:
                stats = google_services.get_study_stats(spreadsheet_id)
            return JsonResponse({"status": "success", "stats": stats})
            
        # ----------------------------------------------------------------
        # フェーズ⑩：AIコーチ設定（性格）取得
        # ----------------------------------------------------------------
        elif phase == "get_personalities":
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            personalities = []
            if spreadsheet_id:
                personalities = google_services.get_personalities(spreadsheet_id)
            return JsonResponse({"status": "success", "personalities": personalities})
            
        else:
            return JsonResponse({"status": "error", "message": "Invalid phase"}, status=400)
            
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

def trigger_voicevox(text: str, speaker_id: int = 47):
    """VOICEVOX ENGINEを叩いてローカルPCで音声を再生する内部関数"""
    try:
        # 音声合成用クエリの作成 (指定されたspeaker_idを使用)
        res_query = requests.post(f"{VOICEVOX_URL}/audio_query", params={"text": text, "speaker": speaker_id}, timeout=5)
        query_data = res_query.json()
        
        # 音声バイナリの生成
        res_synthesis = requests.post(f"{VOICEVOX_URL}/synthesis", params={"speaker": speaker_id}, data=json.dumps(query_data), timeout=10)
        
        # ローカルの static フォルダに保存してフロントエンドから再生できるようにする
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
        os.makedirs(static_dir, exist_ok=True)
        wav_path = os.path.join(static_dir, "current_coaching.wav")
        
        with open(wav_path, "wb") as f:
            f.write(res_synthesis.content)
            
        # 注意: クラウド環境(Cloud Run)ではローカル再生不可のため、
        # 必要に応じてWAVのバイナリ、あるいはURLをGAS側に返却してクライアント側で再生させる設計に切り替える。
    except Exception as e:
        print(f"VOICEVOX連携エラー: {e}")
