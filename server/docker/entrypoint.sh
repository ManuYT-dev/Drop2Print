#!/bin/sh
# Runs once, every time this container starts. Makes sure nothing from a
# previous, unclean shutdown is still running before supervisord takes
# over process management - so starting the container again (or restarting
# after a crash) never ends up with two syncthing / gunicorn / cleanup
# processes fighting over the same files or ports.
set -eu

echo "[entrypoint] clearing any stale processes/locks from a previous run..."
pkill -f "syncthing serve" 2>/dev/null || true
pkill -f "gunicorn" 2>/dev/null || true
pkill -f "cleanup_loop.sh" 2>/dev/null || true

rm -f /var/run/supervisord.pid

mkdir -p "${UPLOAD_FOLDER:-/data/uploads}" /data/syncthing-config

# If no SECRET_KEY was passed in via .env/environment, generate one on
# first start and persist it in the data volume so it survives container
# rebuilds/restarts. Reusing the same key every time matters - if it
# changed on every restart, every open session and CSRF token would break.
SECRET_KEY_FILE="/data/secret_key"
if [ -z "${SECRET_KEY:-}" ]; then
    if [ -f "$SECRET_KEY_FILE" ]; then
        echo "[entrypoint] loading existing SECRET_KEY from $SECRET_KEY_FILE"
    else
        echo "[entrypoint] no SECRET_KEY set - generating one and saving it to $SECRET_KEY_FILE"
        python3 -c "import secrets; print(secrets.token_hex(32))" > "$SECRET_KEY_FILE"
        chmod 600 "$SECRET_KEY_FILE"
    fi
    SECRET_KEY="$(cat "$SECRET_KEY_FILE")"
    export SECRET_KEY
fi

echo "[entrypoint] starting supervisord"
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
