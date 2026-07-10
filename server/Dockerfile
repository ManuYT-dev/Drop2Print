FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UPLOAD_FOLDER=/data/uploads

# supervisor: runs syncthing + the web app + the cleanup loop together.
# procps: gives us pkill/pgrep for entrypoint.sh.
# curl/gnupg2/ca-certificates: needed to add Syncthing's official apt repo.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 ca-certificates supervisor procps libreoffice\
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL -o /etc/apt/keyrings/syncthing-archive-keyring.gpg https://syncthing.net/release-key.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/syncthing-archive-keyring.gpg] https://apt.syncthing.net/ syncthing stable" \
        > /etc/apt/sources.list.d/syncthing.list \
    && apt-get update && apt-get install -y --no-install-recommends syncthing \
    && apt-get purge -y gnupg2 && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ /app/

COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/cleanup_loop.sh /scripts/cleanup_loop.sh
COPY docker/supervisord.conf /etc/supervisor/supervisord.conf
# Strip Windows line endings in case the files were checked out/edited on
# Windows - a CRLF shebang line makes Linux report "no such file or
# directory" even though the file clearly exists.
RUN sed -i 's/\r$//' /entrypoint.sh /scripts/cleanup_loop.sh \
    && chmod +x /entrypoint.sh /scripts/cleanup_loop.sh

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
