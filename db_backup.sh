#!/bin/bash

# CONFIG (match your .env manually)
POSTGRES_USER=silent
POSTGRES_DB=silentempire
CONTAINER_NAME=app-postgres-1

set -e

# Backup file
BACKUP_FILE="/srv/backups/db/silentempire_db_$(date +%F).sql.gz"

# Run backup (inside container)
docker exec $CONTAINER_NAME pg_dump -U $POSTGRES_USER $POSTGRES_DB | gzip > $BACKUP_FILE

# Delete backups older than 7 days
find /srv/backups/db -type f -name "*.gz" -mtime +7 -delete
