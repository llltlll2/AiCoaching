# Google Cloud Platform (GCP) 無料枠デプロイ手順書

本システムを GCP の無料枠（Always Free）の仮想サーバー（Compute Engine）にデプロイし、インターネットに常時公開（HTTPS）するためのステップバイステップマニュアルです。

---

## 📋 全体の流れ
1.  **GCP側での準備** (インスタンス作成、IP固定、ファイアウォール設定)
2.  **ドメインとDNS設定** (ドメインの取得とIPアドレスの紐づけ)
3.  **サーバーの初期構築** (パッケージ導入、Gitクローン、仮想環境構築)
4.  **本番サービス公開** (Gunicorn、Nginx、HTTPS化の適用)
5.  **データバックアップ設定** (SQLite自動日次バックアップのスケジュール化)

---

## 1. GCP側での準備（ブラウザ操作）

### 1.1 VMインスタンス (GCE) の作成
1.  [Google Cloud Console](https://console.cloud.google.com/) にアクセスします。
2.  左メニューから **「Compute Engine」 ＞ 「VM インスタンス」** を選択し、**「インスタンスを作成」** をクリックします。
3.  以下の設定を行います（※これ以外の設定はデフォルトで構いません）：
    *   **名前**: `aicoaching-server`
    *   **リージョン**: `us-central1` (アイオワ), `us-east1` (サウスカロライナ), `us-west1` (オレゴン) のいずれかを選択。（※Always Free無料枠の対象リージョンです）
    *   **ゾーン**: 任意 (例: `us-central1-a`)
    *   **マシン構成**: シリーズ `E2` ＞ マシンタイプ `e2-micro` (2vCPU, 1GBメモリ)。（※Always Free無料枠対象のマシンタイプです）
    *   **ブートディスク**:
        *   「変更」をクリックし、OSに **「Ubuntu」** (バージョン: `Ubuntu 24.04 LTS` または `22.04 LTS`) を選択。
        *   サイズを **「30 GB」**（無料枠の上限）、ブートディスクの種類を **「標準永続ディスク」** に変更。
    *   **ファイアウォール**:
        *   **「HTTP トラフィックを許可する」** にチェック。
        *   **「HTTPS トラフィックを許可する」** にチェック。
4.  最下部の **「作成」** をクリックします。

### 1.2 外部IPアドレスの固定（静的IPの予約）
インスタンスの再起動などでIPアドレスが変わらないように固定します。
1.  GCP検索バーで **「外部 IP アドレス」** を検索して開きます（ネットワークサービス内）。
2.  先ほど作成したVMインスタンスの外部IPの行を探し、タイプを「エフェメラル」から **「静的」** に変更し、適当な名前（例: `aicoaching-static-ip`）を付けて予約します。

---

## 2. ドメインとDNS設定（必要な場合）

HTTPS化（常時暗号化）を行うにはドメインが必要です。お持ちのドメイン管理サービス（お名前.com, Cloudflare, Google Domainsなど）で、DNSレコードを設定してください。
*   **タイプ**: `A`
*   **名前（ホスト）**: `@`（または `coaching` などのサブドメイン）
*   **値（IP）**: GCPで取得した**外部静的IPアドレス**

---

## 3. サーバーの初期構築（SSH接続後の操作）

ここからは、作成したGCP VMの **「SSH」** ボタンをクリックしてターミナルを開き、コマンドを実行します。

### 3.1 必要なシステムパッケージの導入
以下のコマンドをコピーして、ターミナルに貼り付けて実行してください。
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv python3-dev sqlite3 nginx git curl -y
```

### 3.2 ディレクトリの作成とコードの取得
本番用のデプロイディレクトリを作成し、GitHubからリポジトリをクローンします。
```bash
sudo mkdir -p /var/www/aicoaching
sudo chown -R ubuntu:www-data /var/www/aicoaching
cd /var/www/aicoaching

# GitHubからクローン
git clone https://github.com/llltlll2/AiCoaching.git .
```

### 3.3 仮想環境の構築とインストール
Python仮想環境を作成し、必要なライブラリをインストールします。
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.4 環境変数（`.env`）の作成
本番用のシークレットキーやGemini APIキーを環境変数ファイルに記述します。
```bash
nano backend/.env
```
エディタが開いたら、以下の内容を入力します（APIキーやデータベース名を指定します）：
```ini
GEMINI_API_KEY="あなたの_GEMINI_API_KEY_をここに書く"
SECRET_KEY="適当な長い英数字の文字列"
DEBUG=False
ALLOWED_HOSTS="あなたのドメイン名,GCPの外部IPアドレス"
```
入力後、`Ctrl + O` ＞ `Enter` で保存し、`Ctrl + X` でエディタを閉じます。

### 3.5 データベースの初期化と静的ファイルの収集
```bash
cd backend
../venv/bin/python manage.py collectstatic --noinput
../venv/bin/python manage.py migrate
```

---

## 4. 本番サービス公開

### 4.1 Gunicornの起動設定
プロジェクト内に作成済みの `gunicorn.service` 設定ファイルを、システムのシステムサービス管理フォルダへシンボリックリンク（あるいはコピー）し、有効化します。

```bash
# 設定ファイルの配置
sudo cp /var/www/aicoaching/backend/deploy/gunicorn.service /etc/systemd/system/aicoaching.service

# サービスの開始と有効化
sudo systemctl start aicoaching
sudo systemctl enable aicoaching

# 起動ステータスの確認 (Active: active (running) になっていれば成功です)
sudo systemctl status aicoaching
```

### 4.2 NginxのWebサーバー設定
Nginx設定テンプレートを配置し、有効化します。

```bash
# Nginx設定ファイルを配置
sudo cp /var/www/aicoaching/backend/deploy/nginx.conf /etc/nginx/sites-available/aicoaching

# 設定ファイル内の「YOUR_DOMAIN_OR_IP」をご自身のドメイン名（または外部IP）に書き換えます
sudo sed -i 's/YOUR_DOMAIN_OR_IP/あなたのドメイン名/g' /etc/nginx/sites-available/aicoaching

# サイトの有効化と既存のデフォルトサイトの無効化
sudo ln -s /etc/nginx/sites-available/aicoaching /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default

# Nginxの構文チェック
sudo nginx -t

# Nginxの再起動
sudo systemctl restart nginx
```

### 4.3 HTTPS (SSL) の設定
Certbotを導入し、SSLによる通信の暗号化（HTTPS化）を数秒で適用します。

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d あなたのドメイン名
```
（メールアドレスの入力や規約への同意を求められます。指示に従って進めると、自動でNginx設定が更新されHTTPS化が完了します）。

---

## 5. データバックアップの自動スケジュール設定（任意）

SQLiteデータベース（`db.sqlite3`）を安全に保全するため、作成済みのバックアップスクリプトをスケジュール（cron）登録します。

```bash
# スクリプトを実行可能にする
sudo chmod +x /var/www/aicoaching/backend/deploy/backup_db.sh

# スケジュール（毎日午前4時実行）の登録
(crontab -l 2>/dev/null; echo "0 4 * * * /var/www/aicoaching/backend/deploy/backup_db.sh >> /var/log/aicoaching_backup.log 2>&1") | crontab -
```

ローカルバックアップは `/var/www/aicoaching/backups/` に保存され、自動的に過去7日分を維持して古いものはローテーション削除されます。
※クラウド（Cloudflare R2等）へミラーリング退避させる場合は、スクリプト内の `ENABLE_CLOUD_BACKUP=true` に書き換え、`rclone` ツールを設定してください。
