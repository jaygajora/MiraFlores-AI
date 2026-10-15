#!/bin/sh
# Hosted volumes (Render disks, Fly volumes) mount as root. Give the data directory to the
# app user, then run the server without root privileges.
set -eu
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$(dirname "$DB_PATH")"
  chown -R app "$(dirname "$DB_PATH")"
  exec setpriv --reuid=app --regid=app --clear-groups "$@"
fi
exec "$@"
