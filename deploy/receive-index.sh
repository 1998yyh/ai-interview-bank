#!/usr/bin/env bash
set -euo pipefail

site_dir=/var/www/ai-interview-bank
max_bytes=67108864

if [[ -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
  printf '%s\n' 'This key accepts a compressed HTML file on standard input.' >&2
  exit 1
fi

incoming=$(mktemp "$site_dir/incoming/index.XXXXXXXX")
trap 'rm -f -- "$incoming"' EXIT

timeout 90s bash -o pipefail -c 'gzip -dc | head -c "$2" > "$1"' _ "$incoming" "$((max_bytes + 1))"
if (( $(stat -c %s -- "$incoming") > max_bytes )) ||
   [[ $(head -n 1 -- "$incoming") != '<!doctype html>' ]] ||
   ! grep -Fq 'id="bank-data"' "$incoming" ||
   [[ $(tail -n 1 -- "$incoming") != '</html>' ]]; then
  printf '%s\n' 'Invalid interview bank artifact.' >&2
  exit 1
fi

checksum=$(sha256sum -- "$incoming")
chmod 0644 "$incoming"
mv -fT -- "$incoming" "$site_dir/public/index.html"
printf '%s\n' "${checksum%% *}"
