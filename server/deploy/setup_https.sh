#!/bin/bash
# setup_https.sh - Sets up Nginx as an HTTPS reverse proxy in front of the
# Flask container (127.0.0.1:8000) and issues a free Let's Encrypt
# certificate for it via Certbot.
#
# Run this ON THE SERVER (not on your Windows PC), as root or with sudo,
# AFTER you've pointed your domain's DNS at the server (see README) and
# AFTER the Docker container is already running.
#
# Usage:
#   sudo ./setup_https.sh yourdomain.com you@example.com
#
# Safe to re-run: it won't duplicate the Nginx config, and Certbot skips
# re-issuing a certificate that isn't due for renewal yet.

set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
APP_PORT="${3:-8000}"

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Usage: sudo ./setup_https.sh <domain> <email> [app_port]"
    echo "Example: sudo ./setup_https.sh upload.straussdruck.at admin@straussdruck.at"
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "This script needs root privileges. Re-run with: sudo ./setup_https.sh $*"
    exit 1
fi

echo "=== 1/5: Checking DNS ==="
SERVER_IP="$(curl -fsSL https://api.ipify.org || true)"
DOMAIN_IP="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -n1 || true)"

if [ -z "$SERVER_IP" ]; then
    echo "Warning: could not determine this server's public IP - skipping DNS check."
elif [ -z "$DOMAIN_IP" ]; then
    echo "Warning: '$DOMAIN' does not resolve to any IP yet."
    echo "Set an A record for '$DOMAIN' pointing to $SERVER_IP at your DNS provider first,"
    echo "then wait for it to propagate before re-running this script."
    exit 1
elif [ "$DOMAIN_IP" != "$SERVER_IP" ]; then
    echo "Warning: '$DOMAIN' currently resolves to $DOMAIN_IP, but this server's IP is $SERVER_IP."
    echo "Certbot's domain validation will fail until the DNS A record matches."
    read -r -p "Continue anyway? [y/N] " CONTINUE
    if [ "$CONTINUE" != "y" ] && [ "$CONTINUE" != "Y" ]; then
        exit 1
    fi
else
    echo "OK: '$DOMAIN' resolves to this server ($SERVER_IP)."
fi

echo "=== 2/5: Installing Nginx and Certbot ==="
apt-get update -qq
apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx

echo "=== 3/5: Writing Nginx server block ==="
CONF_PATH="/etc/nginx/sites-available/${DOMAIN}.conf"

cat > "$CONF_PATH" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    # Matches the app's own upload limit (see MAX_CONTENT_LENGTH_BYTES in
    # app.py) - without this, Nginx itself would reject large uploads
    # with its own 413 before Flask ever sees them.
    client_max_body_size 60m;

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # Needed so the app can tell an AJAX form submission apart from a
        # plain page load (see wants_json() in app.py).
        proxy_set_header X-Requested-With \$http_x_requested_with;
    }
}
EOF

ln -sf "$CONF_PATH" "/etc/nginx/sites-enabled/${DOMAIN}.conf"

# The default site can conflict with catch-all server_name matching; safe
# to disable since we always access this by the real domain.
if [ -f /etc/nginx/sites-enabled/default ]; then
    rm -f /etc/nginx/sites-enabled/default
fi

nginx -t
systemctl reload nginx

echo "=== 4/5: Requesting the certificate ==="
certbot --nginx \
    -d "$DOMAIN" \
    -m "$EMAIL" \
    --agree-tos \
    --redirect \
    --non-interactive

echo "=== 5/5: Final check ==="
nginx -t
systemctl reload nginx

echo ""
echo "Done. https://${DOMAIN} should now be live and proxying to 127.0.0.1:${APP_PORT}."
echo "Certificates auto-renew via a systemd timer/cron job that Certbot installed;"
echo "check with: sudo certbot renew --dry-run"
