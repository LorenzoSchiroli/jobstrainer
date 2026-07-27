FROM postgres:16-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends rclone \
    && rm -rf /var/lib/apt/lists/*

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod 0555 /usr/local/bin/backup.sh

USER 999
ENTRYPOINT ["/usr/local/bin/backup.sh"]
