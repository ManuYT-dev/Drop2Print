#!/bin/sh
# Deletes submission folders older than MAX_AGE_DAYS from UPLOAD_FOLDER,
# checking every CLEANUP_INTERVAL_SECONDS. Runs forever as a supervisord
# program (one instance - supervisord itself prevents duplicates; the
# container entrypoint also clears any stale copy on startup, see
# entrypoint.sh).
set -eu

UPLOAD_DIR="${UPLOAD_FOLDER:-/data/uploads}"
MAX_AGE_DAYS="${MAX_AGE_DAYS:-1}"
INTERVAL_SECONDS="${CLEANUP_INTERVAL_SECONDS:-3600}"

echo "[cleanup] watching $UPLOAD_DIR, deleting submissions older than $MAX_AGE_DAYS day(s), every ${INTERVAL_SECONDS}s"

while true; do
    # -mtime +0 means "older than 24h"; +1 means "older than 48h", etc.,
    # so we subtract 1 from MAX_AGE_DAYS to match the "N days" phrasing.
    THRESHOLD=$((MAX_AGE_DAYS - 1))
    DELETED=$(find "$UPLOAD_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+$THRESHOLD" -print 2>/dev/null || true)
    if [ -n "$DELETED" ]; then
        echo "$DELETED" | while IFS= read -r dir; do
            echo "[cleanup] removing: $dir"
            rm -rf "$dir"
        done
    fi
    sleep "$INTERVAL_SECONDS"
done
