const BACKEND_URL = "https://flatly-porridge-latch.ngrok-free.dev/api/study_coaching_hub";

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
    "headers": { "ngrok-skip-browser-warning": "true" },
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
    "date": sheet.getRange("B6").getValue(),
    "subject": sheet.getRange("B7").getValue(),
    "progress_volume": sheet.getRange("B8").getValue(),
    "user_memo": sheet.getRange("B9").getValue()
  };
  
  const options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "headers": { "ngrok-skip-browser-warning": "true" },
    "muteHttpExceptions": true
  };
  
  const response = UrlFetchApp.fetch(BACKEND_URL, options);
  const result = JSON.parse(response.getContentText());
  
  if (result.status === "success") {
    // 戻ってきた評価とコメントをスプレッドシートに反映
    sheet.getRange("B12").setValue(result.evaluation.daily_rating);
    
    // コーチングコメントをB13に出力
    sheet.getRange("A13").setValue("コメント:");
    sheet.getRange("B13").setValue(result.evaluation.coaching_comment);
    
    Browser.msgBox("コーチング完了！評価とコメントを確認してください。");
  } else {
    Browser.msgBox("エラーが発生しました: " + (result.message || "不明なエラー"));
  }
}

/**
 * 管理人用の初期セットアップ：スプレッドシートをWebアプリのデータベース用に構築する
 * この関数を1度だけ実行してください。
 */
function setupUI() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // 1. 日々の記録用データベースシート
  let dailySheet = ss.getSheetByName("日々の記録履歴");
  if (!dailySheet) {
    dailySheet = ss.insertSheet("日々の記録履歴");
    dailySheet.getRange("A1:G1").setValues([["日付", "学習テーマ", "学習時間", "進捗", "メモ", "評価", "コメント"]]);
    dailySheet.getRange("A1:G1").setBackground("#2F4F4F").setFontColor("#FFFFFF").setFontWeight("bold");
    dailySheet.setFrozenRows(1);
  }
  
  // 2. 小テスト履歴用データベースシート
  let quizSheet = ss.getSheetByName("小テスト履歴");
  if (!quizSheet) {
    quizSheet = ss.insertSheet("小テスト履歴");
    quizSheet.getRange("A1:G1").setValues([["出題日時", "関連用語", "問題文", "ユーザーの回答", "正解・解説", "正誤判定", "次回の出題予定日"]]);
    quizSheet.getRange("A1:G1").setBackground("#8B0000").setFontColor("#FFFFFF").setFontWeight("bold");
    quizSheet.setFrozenRows(1);
  }

  // 古い入力フォーム（日々の記録入力）が残っていれば注意を促す
  Browser.msgBox("Webアプリ用のデータベース構築（シート作成）が完了しました！\\n以降の入力はすべてWeb画面から行ってください。");
}
