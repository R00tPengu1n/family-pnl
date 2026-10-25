#!/usr/bin/env sh
# Restore a backup made by scripts/backup.sh into a database of the Compose stack.
#
#   scripts/restore.sh <dump-file> [database]     default database: family_pnl_restore
#
# The target database is dropped and created again, so restoring into the scratch default
# never touches the live one. To replace the live database, stop api, worker and bot first
# and name it explicitly (see docs/deploy.md).
set -eu

DUMP="${1:?usage: scripts/restore.sh <dump-file> [database]}"
TARGET="${2:-family_pnl_restore}"

docker compose exec -T -e TARGET="$TARGET" postgres sh -c '
    dropdb -U "$POSTGRES_USER" --if-exists "$TARGET"
    createdb -U "$POSTGRES_USER" "$TARGET"
'
docker compose exec -T -e TARGET="$TARGET" postgres sh -c \
    'pg_restore -U "$POSTGRES_USER" -d "$TARGET" --no-owner --exit-on-error' < "$DUMP"

query() {
    docker compose exec -T -e TARGET="$TARGET" -e SQL="$1" postgres sh -c \
        'psql -U "$POSTGRES_USER" -d "$TARGET" -tAc "$SQL"'
}
echo "restore: $DUMP -> $TARGET, schema $(query 'SELECT version_num FROM alembic_version'), $(query 'SELECT count(*) FROM operations') operations"
