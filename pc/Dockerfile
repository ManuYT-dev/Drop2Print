FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    SYNC_FOLDER=/data/synced-uploads \
    ARCHIVE_FOLDER=/data/archive

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 ca-certificates supervisor procps \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL -o /etc/apt/keyrings/syncthing-archive-keyring.gpg https://syncthing.net/release-key.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/syncthing-archive-keyring.gpg] https://apt.syncthing.net/ syncthing stable" \
        > /etc/apt/sources.list.d/syncthing.list \
    && apt-get update && apt-get install -y --no-install-recommends syncthing \
    && apt-get purge -y gnupg2 && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY docker/file_mover.py /scripts/file_mover.py
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/supervisord.conf /etc/supervisor/supervisord.conf
RUN sed -i 's/\r$//' /entrypoint.sh \
    && chmod +x /entrypoint.sh /scripts/file_mover.py

VOLUME ["/data"]

ENTRYPOINT ["/entrypoint.sh"]
