#!/usr/bin/env bash
# Datacow/DataCrab 每日备份脚本
# 用法: BACKUP_DIR=/data/backups/datacow ./deploy/backup.sh
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/data/backups/datacow}"
PG_CONTAINER="${PG_CONTAINER:-datacow-postgres-1}"
PG_USER="${PG_USER:-datacow}"
PG_DB="${PG_DB:-datacow}"
MINIO_BUCKET="${MINIO_BUCKET:-datacrab}"
KEEP_DAYS="${KEEP_DAYS:-14}"
TODAY="$(date +%F)"

mkdir -p "$BACKUP_DIR/$TODAY"

# PostgreSQL 逻辑备份
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" "$PG_DB" > "$BACKUP_DIR/$TODAY/postgres.sql"

# 应用数据目录（SQLite、技能、知识库）
rsync -a --delete /data/datacrab/backend/data/ "$BACKUP_DIR/$TODAY/backend_data/"

# MinIO 对象存储（可选，需要 mc 客户端）
if command -v mc >/dev/null 2>&1; then
  mc mirror "minio/$MINIO_BUCKET" "$BACKUP_DIR/$TODAY/minio/"
fi

# 清理过期备份
find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +

echo "backup done: $BACKUP_DIR/$TODAY"
