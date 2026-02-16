#!/bin/sh
# Adapt container user to match host PUID/PGID, then drop privileges.
# Inspired by the LinuxServer.io PUID/PGID pattern.

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

echo "Starting with UID=$PUID GID=$PGID"

# Remove the build-time appuser so we can recreate with the correct IDs
deluser appuser 2>/dev/null
delgroup appuser 2>/dev/null

# Reuse existing group if one already has our target GID, otherwise create one
GROUP_NAME=$(awk -F: -v gid="$PGID" '$3 == gid {print $1; exit}' /etc/group)
if [ -z "$GROUP_NAME" ]; then
    addgroup -g "$PGID" appuser
    GROUP_NAME="appuser"
fi

# Reuse existing user if one already has our target UID, otherwise create one
USER_NAME=$(awk -F: -v uid="$PUID" '$3 == uid {print $1; exit}' /etc/passwd)
if [ -z "$USER_NAME" ]; then
    adduser -D -h /app -u "$PUID" -G "$GROUP_NAME" appuser
    USER_NAME="appuser"
fi

# Ensure the data directory is writable
chown "$USER_NAME:$GROUP_NAME" /data

# Drop privileges and exec the CMD
exec su-exec "$USER_NAME" "$@"
