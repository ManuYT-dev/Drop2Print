#!/bin/sh
# Deletes individual files older than MAX_AGE_DAYS.
# ONLY deletes folders if they are fully empty AND their last modification
# was older than MAX_AGE_DAYS.
set -eu

UPLOAD_DIR="${UPLOAD_FOLDER:-/data/uploads}"
MAX_AGE_DAYS="${MAX_AGE_DAYS:-1}"
INTERVAL_SECONDS="${CLEANUP_INTERVAL_SECONDS:-3600}"

echo "[cleanup] watching $UPLOAD_DIR, deleting files and empty folders older than $MAX_AGE_DAYS day(s), every ${INTERVAL_SECONDS}s"

while true; do
    THRESHOLD=$((MAX_AGE_DAYS - 1))

    # 1. Delete individual files older than the threshold
    # -mindepth 2 targets only files inside the submission subdirectories
    find "$UPLOAD_DIR" -mindepth 2 -type f -mtime "+$THRESHOLD" -print 2>/dev/null | while IFS= read -r file; do
        if [ -n "$file" ]; then
            echo "[cleanup] removing old file: $file"
            rm -f "$file"
        fi
    done

    # 2. Delete empty folders ONLY if they haven't been modified in 24+ hours
    # grep -v ignores the .stfolder to ensure the Syncthing marker isn't destroyed
    find "$UPLOAD_DIR" -mindepth 1 -maxdepth 1 -type d -empty -mtime "+$THRESHOLD" -print 2>/dev/null | grep -v '/\.stfolder$' | while IFS= read -r dir; do
        if [ -n "$dir" ]; then
            echo "[cleanup] removing old empty folder: $dir"
            rmdir "$dir"
        fi
    done

    sleep "$INTERVAL_SECONDS"
done