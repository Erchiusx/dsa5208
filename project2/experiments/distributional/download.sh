#!/bin/bash
# macOS-compatible downloader (bash 3.2, BSD stat). One year per invocation.
set -euo pipefail
year=$1; id=$2
raw=~/code/dsa5208-p2/project2/data/raw
out="$raw/rainfall_${year}.csv"; part="$out.partial"
[ -f "$out" ] && { echo "have $year"; exit 0; }
for attempt in 1 2 3 4 5 6; do
  url=$(curl -fsS --retry 4 "https://api-open.data.gov.sg/v1/public/api/datasets/$id/poll-download" | jq -er '.data.url')
  remote=$(curl -fsSL --range 0-0 -D - -o /dev/null "$url" | tr -d '\r' | grep -i '^content-range:' | sed 's|.*/||')
  curl -fL --continue-at - --retry 4 --retry-all-errors --no-progress-meter -o "$part" "$url" || true
  got=$(stat -f %z "$part" 2>/dev/null || echo 0)
  if [ "$got" -eq "$remote" ]; then mv "$part" "$out"; echo "done $year $got"; exit 0; fi
  echo "retry $year ($got/$remote)"; sleep 5
done
exit 1
