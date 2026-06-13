# AI資格取得伴走コーチングシステム 統合設計・実装仕様書

本ドキュメントは、GAS（Google Apps Script）、Django（Python）、Gemini API、およびVOICEVOXを密結合させ、Google Cloud Run上での超低コスト運用を想定した、個人向け「音声伴走型資格学習システム」の全レイヤーにおける設計・実装仕様である。

---

## 1. システムアーキテクチャ (Architecture)

システムは、UIおよびカレンダー描画を担う「Googleスプレッドシート」、中継ハブの「GAS」、ロジック・バッチ・API連携を制御する「Django」、頭脳となる「Gemini API」、音声合成を行う「VOICEVOX」の5つのコンポーネントで構成される。

### 構成レイヤーと役割
1. **Frontend Layer (Google Sheets & GAS)**
   * 管理人が日々の記録、目標設定を行う唯一のインターフェース。
   * GASがシートのデータをJSONに構造化してバックエンドへPOST送信する。
   * 初期化フェーズでは、バックエンドから受け取った計画データを基に、シート上に月間カレンダーを自動描画（レンダリング）する。
2. **Backend API Layer (Django / Google Cloud Run)**
   * Google Cloud Run（サーバーレス）を採用し、リクエスト処理時のみ課金される超低コスト運用を実現。独自ドメインは不要（Google提供のHTTPS URLをそのまま使用）。
   * Google Identity-Aware Proxy (IAP) または固定トークン（APIキー）認証により、管理人以外のアクセスを完全遮断。
   * 参考書PDFなどのバイナリ教材データを内包し、Geminiへのコンテキストインジェクション（RAG）を統括。
3. **AI Brain Layer (Gemini API / gemini-2.5-flash)**
   * 超長文コンテキストを活かし、シラバスや参考書PDFを丸ごと解釈。
   * 出力形式を完全にJSON（Structured Outputs）に固定し、プログラムによる確実なパースを保証。
4. **Voice Synthesis Layer (VOICEVOX Engine)**
   * Djangoから送出されたテキストを、ローカルまたはクラウド上のAPIを介して音声波形（WAV）へ変換。管理人のPCスピーカー（またはスマホ）から音声として再生する。

---

## 2. 処理フローおよびデータ構造 (Data Flow & JSON Schema)

本システムは「①計画策定フェーズ（初期設定）」と「②日々の運用フェーズ（ハイブリッド型）」の2つのモードでデータを還流させる。

### フェーズ①：初期設定（ロードマップ・カレンダー自動生成）
管理人が宣言した資格名と目標期間に基づき、マスタスケジュールとシート上のカレンダー枠を動的に生成する。


```

[管理人: 資格名・期間入力] ➔ [GAS] ➔ (JSON) ➔ [Django] ➔ [Gemini API]
│
[学習管理マスタ・カレンダー自動描画] ↩ [GAS] ── (JSON) ── ↩ [Django]

```

#### GASからDjangoへのリクエスト (POST /api/generate_plan)
```json
{
  "phase": "init",
  "qualification": "応用情報技術者試験",
  "duration_months": 3
}

```

#### DjangoからGASへのレスポンス (JSON Schema)

```json
{
  "status": "success",
  "qualification": "応用情報技術者試験",
  "total_duration_months": 3,
  "milestones": [
    {
      "week": 1,
      "topic": "基礎理論・アルゴリズム",
      "target_progress_percent": 10,
      "description": "離散数学、アルゴリズムの基礎、データ構造の理解"
    },
    {
      "week": 2,
      "topic": "コンピュータ構成要素",
      "target_progress_percent": 20,
      "description": "CPU、メモリ、投射制御、BUS帯域の計算"
    }
  ]
}

```

---

### フェーズ②：日々の運用（学習記録と音声コーチング）

毎日の進捗数値（定量）と学習メモ（定性）をハイブリッド評価し、カレンダーへのフィードバック（セルの自動緑色化）と音声再生を連動させる。

```
[管理人: 進捗・メモ入力] ➔ [GAS] ➔ (JSON) ➔ [Django (PDF等結合)] ➔ [Gemini API]
                                                                      │
[カレンダー着色 (緑色)] ── [GAS] ── [Django] ── (テキスト) ➔ [VOICEVOX] ➔ [音声再生]

```

#### GASからDjangoへのリクエスト (POST /api/daily_report)

```json
{
  "phase": "daily_report",
  "date": "2026-06-13",
  "subject": "コンピュータ構成要素",
  "progress_volume": "15/150",
  "user_memo": "キャッシュメモリのヒット率計算と実効アクセス時間の公式が難しく、少し足止めを食いました。"
}

```

#### DjangoからGASへのレスポンス (JSON Schema)

```json
{
  "daily_rating": "B",
  "progress_status": "delayed_light",
  "coaching_comment": "管理人、キャッシュの実効アクセス時間計算に苦戦されているようですね。等比数列や確率の概念を一度整理すると、スッと腑に落ちますよ。明日は公式の丸暗記ではなく、データの流れを追うことから始めましょう。"
}

```

---

## 3. バックエンド実装 (Django / Python)

### `views.py` (APIエンドポイントの実装)

```python
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import google.generativeai as genai
import requests
import json
import os

# Gemini APIの初期化
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY"))

# VOICEVOX APIの基本URL (ローカル環境想定)
VOICEVOX_URL = "http://localhost:50021"

@csrf_exempt
def study_coaching_hub(request):
    if request.method != 'POST':
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
    
    try:
        # 1. GASからの共通構造化データのパース
        payload = json.loads(request.body)
        phase = payload.get("phase")
        
        # ----------------------------------------------------------------
        # フェーズ①：初期設定（ロードマップ生成）
        # ----------------------------------------------------------------
        if phase == "init":
            qualification = payload.get("qualification")
            duration_months = payload.get("duration_months")
            
            model = genai.GenerativeModel(
                model_name='gemini-2.5-flash',
                generation_config={"response_mime_type": "application/json"},
                system_instruction="あなたは優秀な学習コンサルタントです。指定された資格と期間に基づき、週ごとの学習計画を指定のJSONフォーマットで作成してください。"
            )
            
            prompt = f"資格名: {qualification}, 期間: {duration_months}ヶ月"
            response = model.generate_content(prompt)
            return JsonResponse({"status": "success", "plan": json.loads(response.text)})
            
        # ----------------------------------------------------------------
        # フェーズ②：日々の運用（コーチング＆音声化）
        # ----------------------------------------------------------------
        elif phase == "daily_report":
            user_memo = payload.get("user_memo")
            subject = payload.get("subject")
            progress = payload.get("progress_volume")
            
            # システムプロンプト（NotebookLM的挙動の再現）
            system_instruction = (
                "あなたは優秀な学習伴走コーチ「ファウスト」です。二人称は『管理人』としてください。"
                "すぐ正解を教えず、自発的な気づきを促す段階的なヒントや問いかけを行ってください。"
                "出力は必ず指定されたJSON構造（daily_rating, progress_status, coaching_comment）を厳守してください。"
            )
            
            model = genai.GenerativeModel(
                model_name='gemini-2.5-flash',
                generation_config={"response_mime_type": "application/json"},
                system_instruction=system_instruction
            )
            
            # 本来はここに教材PDF（参考書）をファイルバインドして入力に含める
            prompt = f"本日実施：{subject}, 進捗：{progress}, 管理人メモ：{user_memo}"
            gemini_response = model.generate_content(prompt)
            result_json = json.loads(gemini_response.text)
            
            # VOICEVOXへのブリッジ処理
            coaching_text = result_json.get("coaching_comment", "")
            if coaching_text:
                trigger_voicevox(coaching_text)
                
            return JsonResponse({
                "status": "success",
                "evaluation": result_json
            })
            
        else:
            return JsonResponse({"status": "error", "message": "Invalid phase"}, status=400)
            
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

def trigger_voicevox(text: str):
    """VOICEVOX ENGINEを叩いてローカルPCで音声を再生する内部関数"""
    try:
        # 音声合成用クエリの作成
        res_query = requests.post(f"{VOICEVOX_URL}/audio_query", params={"text": text, "speaker": 1})
        query_data = res_query.json()
        
        # 音声バイナリの生成
        res_synthesis = requests.post(f"{VOICEVOX_URL}/synthesis", params={"speaker": 1}, data=json.dumps(query_data))
        
        # ローカルに一時保存して再生（または再生ライブラリへ直接投入）
        with open("current_coaching.wav", "wb") as f:
            f.write(res_synthesis.content)
            
        # 注意: クラウド環境(Cloud Run)ではローカル再生不可のため、
        # 必要に応じてWAVのバイナリ、あるいはURLをGAS側に返却してクライアント側で再生させる設計に切り替える。
    except Exception as e:
        print(f"VOICEVOX連携エラー: {e}")

```

---

## 5. フロントエンド実装 (GAS / Google Apps Script)

### `Code.gs` (スプレッドシート側からバックエンドを叩くスクリプト)

```javascript
const BACKEND_URL = "https://YOUR-CLOUD-RUN-URL.a.run.app/api/study_coaching_hub"; // または ngrokのURL

/**
 * 初期設定：資格と期間からロードマップを取得し、シートを自動組み立てる
 */
function initializeLearningPlan() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  
  // シート上の入力セルから値を取得する想定
  const qualification = sheet.getRange("B2").getValue(); 
  const durationMonths = sheet.getRange("B3").getValue();
  
  const payload = {
    "phase": "init",
    "qualification": qualification,
    "duration_months": parseInt(durationMonths)
  };
  
  const options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };
  
  const response = UrlFetchApp.fetch(BACKEND_URL, options);
  const result = JSON.parse(response.getContentText());
  
  if (result.status === "success") {
    renderCalendarSheet(result.plan.milestones);
  } else {
    Browser.msgBox("エラーが発生しました: " + result.message);
  }
}

/**
 * バックエンドから取得したJSONデータを元に、カレンダー・進捗表の枠組みを自動描画する
 */
function renderCalendarSheet(milestones) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let targetSheet = ss.getSheetByName("学習カレンダー");
  
  if (!targetSheet) {
    targetSheet = ss.insertSheet("学習カレンダー");
  } else {
    targetSheet.clear();
  }
  
  // ヘッダーの描画
  targetSheet.getRange("A1:D1").setValues([["週", "推奨学習テーマ", "目標進捗率", "実績（完了日）"]]);
  targetSheet.getRange("A1:D1").setBackground("#2F4F4F").setFontColor("#FFFFFF").setFontWeight("bold");
  
  // 各行の動的組み立てと条件付き書式のベース埋め込み
  milestones.forEach((item, index) => {
    const row = index + 2;
    targetSheet.getRange(row, 1, 1, 3).setValues([[
      "第" + item.week + "週",
      item.topic,
      item.target_progress_percent + "%"
    ]]);
  });
  
  // 今日の学習対象をハイライトする等、GAS側のデザイン制御ロジックをここに集約
  SpreadsheetApp.flush();
  Browser.msgBox("学習カレンダーの自動生成が完了しました！");
}

/**
 * 日々の学習実績を送信し、評価をカレンダーに書き戻す
 */
function sendDailyReport() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("日々の記録入力");
  
  // アクティブ行、もしくは最新入力行のデータをパッキング
  const payload = {
    "phase": "daily_report",
    "date": sheet.getRange("B2").getValue(),
    "subject": sheet.getRange("B3").getValue(),
    "progress_volume": sheet.getRange("B4").getValue(),
    "user_memo": sheet.getRange("B5").getValue()
  };
  
  const options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload)
  };
  
  const response = UrlFetchApp.fetch(BACKEND_URL, options);
  const result = JSON.parse(response.getContentText());
  
  if (result.status === "success") {
    // 戻ってきた評価（A〜D）をスプレッドシートの管理行に反映
    // 条件付き書式により、評価が書き込まれたら該当マスの背景色が自動的に「緑色」等に変化するよう事前にシート側で定義する
    sheet.getRange("B6").setValue(result.evaluation.daily_rating);
  }
}

```

---

## 6. インフラ・セキュリティ設計 (Security & Deployment)

1. **アクセス制限 (Identity-Aware Proxy / Token 認証)**
* クラウド展開時、Cloud Runの前段にGoogle Cloudの **IAP (Identity-Aware Proxy)** を配置。管理人のGoogleアカウント（Gmail）でのみ、スマホ・PCからの通信をすべて防壁で保護する。
* GASからの通信を通すため、リクエストヘッダーに専用の固定シークレットトークンを埋め込み、Djangoのカスタムミドルウェアもしくは `views.py` 内部で検証を強制する。


2. **ステートレス運用（データベースコスト0へのアプローチ）**
* プロトタイプ段階における永続化データの書き込み先はすべてGoogleスプレッドシート（GAS側）に集約する。
* Django自体はデータベースとの常時接続を行わない「ステートレス（状態を持たない）な計算・中継ノード」として稼働させることで、Cloud SQLなどの高価なクラウドデータベース常時起動コストを完全に回避し、Cloud Runの無料枠内に全体のランニングコストを収める。
