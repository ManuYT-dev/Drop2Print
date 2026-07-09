#!/bin/sh
# Runs once, every time this container starts. Clears anything left over
# from a previous run before supervisord takes over, so restarting the
# container (e.g. after the PC crashes and Docker Desktop relaunches it)
# never ends up with two syncthing / file_mover processes running at once.
set -eu

echo "[entrypoint] clearing any stale processes/locks from a previous run..."
pkill -f "syncthing serve" 2>/dev/null || true

rm -f /var/run/supervisord.pid

mkdir -p "${SYNC_FOLDER:-/data/synced-uploads}" /data/syncthing-config

echo "[entrypoint] starting supervisord"
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
