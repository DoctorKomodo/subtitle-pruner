#!/bin/sh
# Adapt container user to match host PUID/PGID, then drop privileges.
# Inspired by the LinuxServer.io PUID/PGID pattern.

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

echo "Starting with UID=$PUID GID=$PGID"

# Update appuser's group and user IDs to match the requested ones
if [ "$(id -g appuser)" != "$PGID" ]; then
    delgroup appuser 2>/dev/null
    addgroup -g "$PGID" appuser
fi

if [ "$(id -u appuser)" != "$PUID" ]; then
    deluser appuser 2>/dev/null
    adduser -D -h /app -u "$PUID" -G appuser appuser
fi

# Ensure appuser owns the data directory
chown appuser:appuser /data

# Drop to appuser and exec the CMD
exec su-exec appuser "$@"
