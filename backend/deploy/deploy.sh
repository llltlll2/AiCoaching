#!/bin/bash
# deploy.sh - All-in-one automatic deployment script for AI Coaching Platform
# Intended to be run on a clean Ubuntu 22.04 / 24.04 LTS instance.

set -e

echo "=================================================="
echo " Starting AI Coaching Platform Auto-Deployment"
echo "=================================================="

# 1. Update and install dependencies
echo "[1/6] Installing system dependencies..."
sudo apt update
sudo apt install python3-pip python3-venv python3-dev sqlite3 nginx git curl -y

# 2. Setup deploy directory
echo "[2/6] Setting up directory structures..."
DEPLOY_DIR="/var/www/aicoaching"
CURRENT_USER=$(whoami)
sudo mkdir -p "${DEPLOY_DIR}"
sudo chown -R "${CURRENT_USER}":www-data "${DEPLOY_DIR}"

# Clone the latest codebase into deploy directory
if [ -d "${DEPLOY_DIR}/.git" ]; then
    echo "Directory already cloned. Pulling latest updates..."
    cd "${DEPLOY_DIR}"
    git fetch origin
    git reset --hard origin/main
else
    echo "Cloning repository..."
    git clone https://github.com/llltlll2/AiCoaching.git "${DEPLOY_DIR}"
    cd "${DEPLOY_DIR}"
fi

# 3. Create Python virtual environment and install requirements
echo "[3/6] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure environment variables (.env)
echo "[4/6] Configuring environment variables..."
ENV_FILE="${DEPLOY_DIR}/backend/.env"

if [ -f "${ENV_FILE}" ]; then
    # Check if the .env file is corrupted or contains invalid domain references
    temp_hosts=$(grep "^ALLOWED_HOSTS" "${ENV_FILE}" || true)
    if [ -z "${temp_hosts}" ] || echo "${temp_hosts}" | grep -q -E "YOUR_DOMAIN|#|Initialize|Settings"; then
        echo "Detected corrupted or invalid .env file. Removing it to recreate..."
        rm -f "${ENV_FILE}"
    fi
fi

if [ ! -f "${ENV_FILE}" ]; then
    echo "Creating new .env file..."
    read -p "Enter your GEMINI_API_KEY: " gemini_key
    read -p "Enter your domain name (or press Enter to use server IP): " user_domain
    user_domain=$(echo "${user_domain}" | tr -d '\r\n' | xargs)
    
    # Get current external IP if no domain is provided
    if [ -z "${user_domain}" ]; then
        user_domain=$(curl -s https://ipinfo.io/ip | tr -d '\r\n')
        if [ -z "${user_domain}" ]; then
            user_domain="_"
        fi
        echo "Using server IP as domain: ${user_domain}"
    fi

    secret_key=$(python3 -c "import secrets; print(secrets.token_hex(24))")

    cat <<EOF > "${ENV_FILE}"
GEMINI_API_KEY="${gemini_key}"
SECRET_KEY="${secret_key}"
DEBUG=False
ALLOWED_HOSTS="${user_domain},localhost,127.0.0.1"
EOF
else
    echo ".env file already exists. Skipping creation."
    user_domain=$(grep "^ALLOWED_HOSTS" "${ENV_FILE}" | head -n 1 | cut -d'"' -f2 | cut -d',' -f1 | tr -d '\r\n' | xargs)
    if [ -z "${user_domain}" ]; then
        user_domain=$(curl -s https://ipinfo.io/ip | tr -d '\r\n')
        if [ -z "${user_domain}" ]; then
            user_domain="_"
        fi
    fi
fi

# 5. Initialize Database & Static Assets
echo "[5/6] Migrating database and collecting static assets..."
cd "${DEPLOY_DIR}/backend"
../venv/bin/python manage.py collectstatic --noinput
../venv/bin/python manage.py migrate

# 6. Configure system services (Gunicorn & Nginx)
echo "[6/6] Setting up system services..."

# Gunicorn
sudo cp "${DEPLOY_DIR}/backend/deploy/gunicorn.service" /etc/systemd/system/aicoaching.service
sudo sed -i "s/User=ubuntu/User=${CURRENT_USER}/g" /etc/systemd/system/aicoaching.service
sudo sed -i 's/\r//g' /etc/systemd/system/aicoaching.service
sudo systemctl daemon-reload
sudo systemctl start aicoaching
sudo systemctl enable aicoaching

# Nginx
sudo cp "${DEPLOY_DIR}/backend/deploy/nginx.conf" /etc/nginx/sites-available/aicoaching
echo "Replacing YOUR_DOMAIN_OR_IP with: '${user_domain}'"
sudo sed -i "s/YOUR_DOMAIN_OR_IP/${user_domain}/g" /etc/nginx/sites-available/aicoaching
sudo sed -i 's/\r//g' /etc/nginx/sites-available/aicoaching

echo "--- Generated Nginx Config ---"
cat /etc/nginx/sites-available/aicoaching
echo "------------------------------"

# Link and enable site in Nginx
sudo rm -f /etc/nginx/sites-enabled/aicoaching
sudo ln -s /etc/nginx/sites-available/aicoaching /etc/nginx/sites-enabled/

# Remove default site if exists
if [ -f /etc/nginx/sites-enabled/default ]; then
    sudo rm /etc/nginx/sites-enabled/default
fi

# Test and restart Nginx
sudo nginx -t
sudo systemctl restart nginx

# Setup Backup Cron Job
echo "Setting up SQLite3 database backup cron job (runs daily at 4:00 AM)..."
sudo chmod +x "${DEPLOY_DIR}/backend/deploy/backup_db.sh"
(crontab -l 2>/dev/null | grep -v "backup_db.sh"; echo "0 4 * * * /var/www/aicoaching/backend/deploy/backup_db.sh >> /var/log/aicoaching_backup.log 2>&1") | crontab -

echo "=================================================="
echo " Deployment completed successfully!"
echo " Access your app at: http://${user_domain}/"
echo "=================================================="
echo "To secure your app with HTTPS, run: "
echo "  sudo apt install certbot python3-certbot-nginx -y"
echo "  sudo certbot --nginx -d ${user_domain}"
echo "=================================================="
