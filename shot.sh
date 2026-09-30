#!/bin/bash
# Screenshot of the panel via its HTTP API: ./shot.sh OUT.png [host]
OUT=${1:-/tmp/panel.png}
HOST=${2:-${PANEL_HOST:-192.168.4.1}}
curl -s -m 60 -o "$OUT" "http://$HOST/api/screenshot" && echo "wrote $OUT ($(stat -c %s "$OUT") bytes)"
