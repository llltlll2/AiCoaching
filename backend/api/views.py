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
            qualification = payload.get("qualification", "")
            query = payload.get("query")
            speaker_id = payload.get("speaker_id", 47)
            
            spreadsheet_id = os.environ.get("SPREADSHEET_ID")
            past_consultations = []
            roadmap = []
            
            if spreadsheet_id and qualification:
                past_consultations = google_services.get_past_consultations(spreadsheet_id, qualification)
                roadmap = google_services.get_roadmap(spreadsheet_id, qualification)
                
            # プロンプトの構成
            history_text = "\n".join([f"過去の相談({c['date']}): {c['query']}\nAI回答: {c['response']}" for c in past_consultations[-5:]])
            roadmap_text = "\n".join([f"第{r['week']}週: {r['topic']} (目標: {r['target_progress_percent']}%, {r['recommended_hours']})" for r in roadmap])
            
            base_prompt = payload.get("system_prompt", "あなたは優秀な学習コンサルタントです。ユーザーからの学習計画に関する相談に乗ります。")
            system_instruction = base_prompt + (
                "\n\n【動作ルール】\n"
                "1. ユーザーとの対話を通じて、資格取得などの目標に向けたロードマップ（スケジュール調整）を行います。\n"
                "2. ユーザーから「学習計画を作りたい」「期間は〇ヶ月」「週〇時間勉強できる」「第〇週は予定がある」などの情報や調整依頼があった場合、それに合わせた週単位のロードマップを設計・更新してください。\n"
                "3. ロードマップを作成・更新した場合は、返送するJSONに必ず `milestones` キーを含めてください。計画の変更や作成を行わずに雑談やアドバイスだけで済む場合は、`milestones` キーを含めないか `null` にしてください。\n"
                "4. もし目標とする資格名が不明な場合は、まず何を目指しているかチャットでユーザーに尋ねてください。\n\n"
                "【JSON構造】必ず以下の有効なJSONのみを出力してください。Markdownブロックは不要です。\n"
                "{\n"
                "  \"advice\": \"ユーザーへのアドバイスや、ロードマップを作成・調整した旨のコメント\",\n"
                "  \"milestones\": [\n"
                "    {\n"
                "      \"week\": 1,\n"
                "      \"topic\": \"今週の主な学習テーマ (例: データベース基礎)\",\n"
                "      \"target_progress_percent\": 10,\n"
                "      \"recommended_hours\": \"平日1時間、休日2時間 (計9時間)\",\n"
                "      \"description\": \"具体的な学習内容やアドバイス\"\n"
                "    }\n"
                "  ]\n"
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
    """Trigger VOICEVOX via public Web API (TTS Quest)"""
    try:
        api_url = "https://api.tts.quest/v3/voicevox/synthesis"
        params = {
            "text": text,
            "speaker": speaker_id
        }
        api_key = os.environ.get("TTS_QUEST_API_KEY")
        if api_key:
            params["key"] = api_key
            
        print(f"VOICEVOX WebAPI request: '{text[:15]}...' (Speaker: {speaker_id})")
        res = requests.get(api_url, params=params, timeout=10)
        res.raise_for_status()
        res_data = res.json()
        
        if not res_data.get("success"):
            print(f"VOICEVOX WebAPI error: {res_data.get('errorMessage')}")
            return
            
        wav_url = res_data.get("wavDownloadUrl")
        audio_status_url = res_data.get("audioStatusUrl")

        if not wav_url:
            print("VOICEVOX WebAPI error: wavDownloadUrl not found.")
            return
            
        if audio_status_url:
            print(f"Polling audio status at {audio_status_url}")
            for _ in range(60): # Max wait time: 60 seconds
                try:
                    status_res = requests.get(audio_status_url, timeout=10)
                    status_res.raise_for_status()
                    status_data = status_res.json()
                    if status_data.get("isAudioReady"):
                        print("Audio generation completed.")
                        break
                    time.sleep(1)
                except Exception as poll_e:
                    print(f"Polling error: {poll_e}")
                    time.sleep(1)

        print(f"Downloading audio file: {wav_url}")
        audio_res = requests.get(wav_url, timeout=30)
        audio_res.raise_for_status()
        
        # Ensure we actually downloaded an audio file instead of a JSON error
        if len(audio_res.content) < 1000 and b"{" in audio_res.content[:5]:
            print(f"VOICEVOX WebAPI downloaded file is invalid (likely an error JSON): {audio_res.content[:100]}")
            return

        from django.conf import settings
        # Use STATIC_ROOT in production to let Nginx serve it, fallback to static directory in development
        if getattr(settings, 'STATIC_ROOT', None):
            static_dir = str(settings.STATIC_ROOT)
        else:
            static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
            
        os.makedirs(static_dir, exist_ok=True)
        wav_path = os.path.join(static_dir, "current_coaching.wav")
        
        with open(wav_path, "wb") as f:
            f.write(audio_res.content)
        print("Audio file saved successfully.")
    except Exception as e:
        print(f"VOICEVOX error: {e}")


import logging
from concurrent.futures import ThreadPoolExecutor
from django.db import transaction, close_old_connections
from .models import Session, Message, SessionSummary

logger = logging.getLogger(__name__)
# Max 1 thread to process summaries sequentially and avoid database lock issues
summary_executor = ThreadPoolExecutor(max_workers=1)

def update_session_summary_task(session_id):
    """
    Background thread execution task for creating and updating SessionSummary.
    """
    try:
        close_old_connections()
        
        session = Session.objects.get(id=session_id)
        existing_summary = SessionSummary.objects.filter(session=session).first()
        summary_text_old = existing_summary.summary_text if existing_summary else "過去の学習要約はありません。"
        
        # Fetch the last 10 messages
        recent_messages = Message.objects.filter(session=session).order_by('-sent_at')[:10]
        # Reverse to chronological order
        recent_messages = list(recent_messages)[::-1]
        
        if not recent_messages:
            return
            
        messages_formatted = "\n".join([
            f"- {msg.sender_role}: {msg.content}" for msg in recent_messages
        ])
        
        system_instruction = (
            "あなたは「AI資格取得伴走コーチングシステム」の会話要約生成エンジンです。\n"
            "これまでの「過去の学習要約」と「直近の対話履歴」を分析し、ユーザーの学習状況に関する最新の要約コンテキストを作成・更新してください。\n\n"
            "# 目的\n"
            "学習者が今何に困っているか、どこまで理解したか、コーチ（ファウスト）が何を指導したかを正確に記録し、次回のAIコーチの対話品質と文脈一貫性を向上させる。\n\n"
            "# 出力フォーマット\n"
            "必ず以下のMarkdown構造を厳格に守って出力してください。これ以外の挨拶や解説は一切含めないでください。\n\n"
            "# 学習要約コンテキスト\n\n"
            "## つまずいたポイント\n"
            "* [ユーザーが混乱している概念、解けない問題、疑問に思っていることなどを記述]\n\n"
            "## 理解度\n"
            "* [ユーザーが正しく理解できた概念、克服したつまずき、進捗などを記述]\n\n"
            "## コーチからのアドバイス\n"
            "* [AIコーチが提示した重要な学習方針、解説の要点、励ましのメッセージなどを記述]\n\n"
            "# 要約更新・差分アップデートのルール\n"
            "1. 過去の要約と直近の会話履歴を論理的に統合し、差分のみを反映してください。\n"
            "2. 解決されたつまずきは「理解度」へ移動してください。\n"
            "3. 改行含め、出力全体の文字数を「800文字以下」に抑えてください。"
        )
        
        prompt = f"""
---
## 過去の学習要約:
{summary_text_old}

---
## 直近の対話履歴:
{messages_formatted}
"""
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.error("Gemini API key is not configured for summary task.")
            return
            
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        
        new_summary_text = response.text.strip()
        
        with transaction.atomic():
            summary_obj, created = SessionSummary.objects.get_or_create(
                session=session,
                defaults={'summary_text': new_summary_text}
            )
            if not created:
                summary_obj.summary_text = new_summary_text
                summary_obj.save()
                
        logger.info(f"Successfully updated summary for session: {session_id}")
        
    except Exception as e:
        logger.error(f"Failed to update session summary for {session_id}: {str(e)}", exc_info=True)
    finally:
        close_old_connections()


@csrf_exempt
def session_list_create(request):
    """
    GET: List all coaching sessions.
    POST: Create a new session.
    """
    if request.method == 'GET':
        sessions = Session.objects.all().order_by('-created_at')
        data = [{
            "id": str(s.id),
            "certification_name": s.certification_name,
            "created_at": s.created_at.isoformat(),
            "status": s.status
        } for s in sessions]
        return JsonResponse(data, safe=False)
        
    elif request.method == 'POST':
        try:
            payload = json.loads(request.body)
            cert_name = payload.get("certification_name")
            if not cert_name:
                return JsonResponse({"error": "certification_name is required"}, status=400)
            
            session = Session.objects.create(certification_name=cert_name)
            return JsonResponse({
                "id": str(session.id),
                "certification_name": session.certification_name,
                "created_at": session.created_at.isoformat(),
                "status": session.status
            }, status=201)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
            
    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
def session_history(request, id):
    """
    GET: Retrieve messages history and current summary for a session.
    """
    if request.method != 'GET':
        return JsonResponse({"error": "Method not allowed"}, status=405)
        
    try:
        session = Session.objects.get(id=id)
        messages = Message.objects.filter(session=session).order_by('sent_at')
        summary = SessionSummary.objects.filter(session=session).first()
        
        msg_data = [{
            "id": str(m.id),
            "sender_role": m.sender_role,
            "sent_at": m.sent_at.isoformat(),
            "content": m.content,
            "rating": m.rating,
            "progress_status": m.progress_status
        } for m in messages]
        
        return JsonResponse({
            "session": {
                "id": str(session.id),
                "certification_name": session.certification_name,
                "created_at": session.created_at.isoformat(),
                "status": session.status
            },
            "summary": {
                "summary_text": summary.summary_text if summary else "",
                "updated_at": summary.updated_at.isoformat() if summary else None
            },
            "messages": msg_data
        })
    except Session.DoesNotExist:
        return JsonResponse({"error": "Session not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def session_message(request, id):
    """
    POST: Send a new message, generate AI response using background context, and trigger summary update.
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return JsonResponse({"error": "Gemini API key not found"}, status=500)
    client = genai.Client(api_key=api_key)
    
    try:
        session = Session.objects.get(id=id)
        payload = json.loads(request.body)
        user_content = payload.get("content")
        speaker_id = payload.get("speaker_id", 47)
        trigger_summary = payload.get("trigger_summary", False)
        
        if not user_content:
            return JsonResponse({"error": "content is required"}, status=400)
            
        # 1. Save user message
        user_msg = Message.objects.create(
            session=session,
            sender_role='user',
            content=user_content
        )
        
        # 2. Load latest summary context
        summary = SessionSummary.objects.filter(session=session).first()
        summary_text = summary.summary_text if summary else "過去の学習要約はありません。"
        
        # 3. Build system instruction prompt with injected background context
        system_instruction = (
            "あなたは資格試験合格を目指すユーザーを全力でサポートする、AI伴走コーチの「ファウスト」です。\n"
            "学習者に対して、信頼できる熱血メンターとして接してください。\n\n"
            "# 過去の学習状況 (BACKGROUND_CONTEXT)\n"
            "以下のコンテキストは、これまでの学習セッションで記録されたユーザーの状況です。\n"
            "このつまずきや理解状況を意識した自然な対話を行ってください。\n\n"
            "<BACKGROUND_CONTEXT>\n"
            f"{summary_text}\n"
            "</BACKGROUND_CONTEXT>\n\n"
            "# 指導・対話ルール\n"
            "1. つまずきがある場合は、過去の文脈を自然に引き出して対話を行ってください。\n"
            "2. 理解した内容は大いに褒めてください。\n"
            "3. 応答は必ず次のJSON形式（有効なJSONのみ）で返却してください。Markdownのjsonブロック等は一切不要です。\n\n"
            "{\n"
            "  \"coaching_comment\": \"ユーザーへの指導や励ましのコメント全文\",\n"
            "  \"daily_rating\": \"理解度の評価 (A/B/C/D のいずれか一文字)\",\n"
            "  \"progress_status\": \"今回のやり取りから判断したユーザーの理解の深まり具合や進捗状況の要約\"\n"
            "}"
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        
        result_json = extract_json(response.text)
        coaching_comment = result_json.get("coaching_comment", "解説を生成できませんでした。")
        rating = result_json.get("daily_rating", "C")
        progress_status = result_json.get("progress_status", "進捗確認なし")
        
        # 4. Save AI response
        assistant_msg = Message.objects.create(
            session=session,
            sender_role='assistant',
            content=coaching_comment,
            rating=rating,
            progress_status=progress_status
        )
        
        # 5. synthesis VOICEVOX speech
        if coaching_comment:
            try:
                trigger_voicevox(coaching_comment, speaker_id)
            except Exception as vx_err:
                print(f"VOICEVOX audio trigger failed: {vx_err}")
                
        # 6. Check summary update trigger (3-turn cycle = 6 messages)
        msg_count = Message.objects.filter(session=session).count()
        if trigger_summary or (msg_count > 0 and msg_count % 6 == 0):
            summary_executor.submit(update_session_summary_task, str(session.id))
            
        return JsonResponse({
            "user_message": {
                "id": str(user_msg.id),
                "sender_role": user_msg.sender_role,
                "sent_at": user_msg.sent_at.isoformat(),
                "content": user_msg.content
            },
            "assistant_message": {
                "id": str(assistant_msg.id),
                "sender_role": assistant_msg.sender_role,
                "sent_at": assistant_msg.sent_at.isoformat(),
                "content": assistant_msg.content,
                "rating": assistant_msg.rating,
                "progress_status": assistant_msg.progress_status
            }
        }, status=201)
        
    except Session.DoesNotExist:
        return JsonResponse({"error": "Session not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
