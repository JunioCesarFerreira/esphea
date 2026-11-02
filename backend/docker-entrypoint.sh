#!/bin/sh
# Run the command as the owner of the data directory, never as root.
#
# With a bind mount (./data:/data) the owner is the host user, so snapshots
# written by the containers stay readable and writable on the host without
# any configuration. A root-owned directory falls back to the image user.
set -eu

data_dir="${ESPHEA_DATA_DIR:-/data}"

if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

mkdir -p "$data_dir"
uid="$(stat -c %u "$data_dir")"
gid="$(stat -c %g "$data_dir")"
if [ "$uid" = "0" ]; then
    uid="$(id -u esphea)"
    gid="$(id -g esphea)"
    chown "$uid:$gid" "$data_dir"
fi

exec setpriv --reuid="$uid" --regid="$gid" --clear-groups -- "$@"
