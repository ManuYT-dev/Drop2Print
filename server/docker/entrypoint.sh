#!/bin/sh
set -eu

echo "[entrypoint] clearing any stale processes/locks from a previous run..."
pkill -f "syncthing serve" 2>/dev/null || true
pkill -f "gunicorn" 2>/dev/null || true
pkill -f "cleanup_loop.sh" 2>/dev/null || true

rm -f /var/run/supervisord.pid
mkdir -p "${UPLOAD_FOLDER:-/data/uploads}" /data/syncthing-config

SECRET_KEY_FILE="/data/secret_key"
if [ -z "${SECRET_KEY:-}" ]; then
    if [ -f "$SECRET_KEY_FILE" ]; then
        echo "[entrypoint] loading existing SECRET_KEY from $SECRET_KEY_FILE"
    else
        echo "[entrypoint] no SECRET_KEY set - generating one and saving it to $SECRET_KEY_FILE"
        python3 -c "import secrets; print(secrets.token_hex(32))" > "$SECRET_KEY_FILE"
        chmod 600 "$SECRET_KEY_FILE"
    fi
    export SECRET_KEY="$(cat "$SECRET_KEY_FILE")"
fi

(
    sleep 5
    echo "[entrypoint] Fetching public IP..."
    REAL_IP=$(curl -s https://api.ipify.org || echo "localhost")
    echo ""
    echo "======================================================="
    echo "🚀 ALL SERVICES STARTED SUCCESSFULLY!"
    echo "🌐 Drop2Print Web Portal is running at: http://${REAL_IP}:8000"
    echo "   (Note: Syncthing P2P connections operate silently in the background)"
    echo "======================================================="
    echo ""
) &
# ------------------------------------------------------------------

echo "[entrypoint] starting supervisord"
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf