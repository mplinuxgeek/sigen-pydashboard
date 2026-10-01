#!/bin/bash
# Screenshot of the panel via its HTTP API.   PANEL_HOST=192.168.1.50 ./shot.sh [OUT.png]      or      ./shot.sh OUT.png HOST
. "$(dirname "$0")/scripts/common.sh"
OUT=${1:-panel.png}
[ -n "${2:-}" ] && PANEL_HOST=$2
need_host
curl -s -m 60 -o "$OUT" "http://$PANEL_HOST/api/screenshot" && echo "wrote $OUT ($(stat -c %s "$OUT" 2>/dev/null || stat -f %z "$OUT") bytes)"
