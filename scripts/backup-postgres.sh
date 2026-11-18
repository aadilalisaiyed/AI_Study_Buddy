#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${PGDATABASE:?Set PGDATABASE via libpq settings}"
: "${1:?Supply a private backup directory outside the repository}"
dir=$1
mkdir -p -- "$dir"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
tmp=$(mktemp "$dir/studybuddy-$stamp-XXXXXX")
trap 'rm -f -- "$tmp"' EXIT
pg_dump --format=custom --compress=6 --no-owner --no-privileges --file="$tmp"
pg_restore --list "$tmp" >/dev/null
archive="$tmp.dump"
mv -n -- "$tmp" "$archive"
printf '%s\n' "$archive"
