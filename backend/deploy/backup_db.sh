#!/bin/bash
# backup_db.sh - Safe SQLite3 online backup script

# Configuration
DB_PATH="/var/www/aicoaching/backend/db.sqlite3"
BACKUP_DIR="/var/www/aicoaching/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/backup_${DATE}.sqlite3"
GZ_FILE="${BACKUP_FILE}.gz"

# Optional Cloud Storage (e.g. Cloudflare R2 / AWS S3)
# Set to true and configure rclone if you want cloud replication
ENABLE_CLOUD_BACKUP=false
RCLONE_REMOTE_PATH="r2-coaching-backup:my-bucket/db/"

# Create local backup directory
mkdir -p "${BACKUP_DIR}"

echo "Starting SQLite3 online backup..."

# 1. Execute safe online backup (flushes and merges WAL safely)
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"

if [ $? -eq 0 ]; then
    echo "Backup created successfully: ${BACKUP_FILE}"
    
    # 2. Compress the backup file to save space
    gzip "${BACKUP_FILE}"
    
    # 3. Optional: Push to Cloud Storage
    if [ "${ENABLE_CLOUD_BACKUP}" = true ]; then
        echo "Uploading to Cloud Storage..."
        rclone copy "${GZ_FILE}" "${RCLONE_REMOTE_PATH}"
        if [ $? -eq 0 ]; then
            echo "Cloud upload successful."
        else
            echo "Warning: Cloud upload failed." >&2
        fi
    fi
    
    # 4. Local rotation: Keep last 7 days of backups and delete older
    find "${BACKUP_DIR}" -type f -name "backup_*.sqlite3.gz" -mtime +7 -delete
    echo "Local backup rotation complete."
else
    echo "Error: SQLite3 backup failed." >&2
    exit 1
fi
