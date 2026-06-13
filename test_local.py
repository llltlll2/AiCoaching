import requests
import json
import time

url = "http://localhost:8000/api/study_coaching_hub"

print("=== 1. 初期設定 (init) のテスト ===")
init_payload = {
    "phase": "init",
    "qualification": "応用情報技術者試験",
    "duration_months": 3
}

try:
    response = requests.post(url, json=init_payload)
    print(f"Status Code: {response.status_code}")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Error: {e}")

print("\n=== 2. 日々の運用 (daily_report) のテスト ===")
daily_payload = {
    "phase": "daily_report",
    "date": "2026-06-13",
    "subject": "コンピュータ構成要素",
    "progress_volume": "15/150",
    "user_memo": "キャッシュメモリのヒット率計算と実効アクセス時間の公式が難しく、少し足止めを食いました。"
}

try:
    response = requests.post(url, json=daily_payload)
    print(f"Status Code: {response.status_code}")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    print("\n※VOICEVOXが起動していれば、'current_coaching.wav' が生成され、ナースロボ＿タイプＴの声で再生されるはずです。")
except Exception as e:
    print(f"Error: {e}")
