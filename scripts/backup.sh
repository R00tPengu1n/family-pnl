#!/usr/bin/env sh
# Daily PostgreSQL backup of the Compose stack, with rotation (see docs/deploy.md).
#
#   scripts/backup.sh [backup-dir]        default: ./backups
#
# Writes <dir>/daily/family_pnl-<date>.dump (pg_dump custom format, compressed); on Sundays
# also keeps a copy in <dir>/weekly. Keeps the 7 newest daily and 4 newest weekly dumps.
# Run from the repository on the server, e.g. from cron at 03:30:
#   30 3 * * * cd /opt/family-pnl && scripts/backup.sh >> backups/backup.log 2>&1
set -eu

DIR="${1:-./backups}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
STAMP="$(date +%Y-%m-%d)"
NAME="family_pnl-${STAMP}.dump"

mkdir -p "$DIR/daily" "$DIR/weekly"

# The dump is written next to its final name first, so a failed run leaves no
# half-written file that looks like a backup.
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$DIR/daily/$NAME.partial"
mv "$DIR/daily/$NAME.partial" "$DIR/daily/$NAME"

if [ "$(date +%u)" = "7" ]; then
    cp "$DIR/daily/$NAME" "$DIR/weekly/$NAME"
fi

# Newest first by name (the date sorts), everything after the first N is removed.
prune() {
    ls -1 "$1"/family_pnl-*.dump 2>/dev/null | sort -r | tail -n "+$(($2 + 1))" | while read -r old; do
        rm -f "$old"
    done
}
prune "$DIR/daily" "$KEEP_DAILY"
prune "$DIR/weekly" "$KEEP_WEEKLY"

echo "backup: $DIR/daily/$NAME ($(wc -c < "$DIR/daily/$NAME") bytes)"
