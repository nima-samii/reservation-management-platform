#!/bin/sh
set -e

# /app/data is a host bind mount (docker-compose.yml `./data:/app/data`). When
# Docker auto-creates the host directory it is owned by root:root, which the
# non-root appuser cannot write to — breaking save_settings_override(). Fix
# ownership here (we start as root), then drop privileges for the real command.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/data
    chown -R appuser:appgroup /app/data
    exec setpriv --reuid appuser --regid appgroup --clear-groups "$@"
fi

exec "$@"
