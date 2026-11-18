#!/usr/bin/env bash
set -euo pipefail
: "${PGDATABASE:?Set PGDATABASE to the source/maintenance database}"
: "${1:?Supply a pg_dump custom archive}"
: "${2:?Supply a new database named studybuddy_restore_<suffix>}"
archive=$1
target=$2
[[ "$target" =~ ^studybuddy_restore_[a-z0-9_]{1,35}$ && "$target" != "$PGDATABASE" ]] || {
  printf 'Refusing unsafe restore target\n' >&2
  exit 2
}
pg_restore --list "$archive" >/dev/null
createdb --maintenance-db="$PGDATABASE" "$target"
pg_restore --dbname="$target" --single-transaction --exit-on-error --no-owner --no-privileges "$archive"
