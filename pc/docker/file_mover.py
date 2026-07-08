#!/usr/bin/env python3
"""
Watches the Syncthing-synced upload folder and moves each fully-received
submission folder into a permanent archive folder that sits outside the
synced tree (so the server's daily cleanup can never touch it).

A submission is only moved once its "_complete.flag" marker - written
last by the Flask app on the server, after every file has landed on
disk - has itself arrived here. That guarantees we never move a folder
that's still mid-sync.
"""

import os
import shutil
import time
from pathlib import Path

SYNC_DIR = Path(os.environ.get("SYNC_FOLDER", "/data/synced-uploads"))
ARCHIVE_DIR = Path(os.environ.get("ARCHIVE_FOLDER", "/data/archive"))
POLL_SECONDS = float(os.environ.get("MOVER_POLL_SECONDS", "5"))
COMPLETE_MARKER = "_complete.flag"


def move_ready_submissions() -> None:
    if not SYNC_DIR.exists():
        return

    for entry in SYNC_DIR.iterdir():
        if not entry.is_dir():
            continue

        marker = entry / COMPLETE_MARKER
        if not marker.exists():
            continue  # still syncing - leave it alone for now

        destination = ARCHIVE_DIR / entry.name
        if destination.exists():
            continue  # already archived, or a name collision - don't overwrite

        try:
            shutil.move(str(entry), str(destination))
            print(f"[file_mover] archived: {entry.name}", flush=True)
        except OSError as exc:
            print(f"[file_mover] failed to move {entry.name}: {exc}", flush=True)


def main() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[file_mover] watching {SYNC_DIR} -> {ARCHIVE_DIR} every {POLL_SECONDS}s", flush=True)
    while True:
        move_ready_submissions()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
