#!/bin/bash
# Push the Python app (py/) to the panel over the network: ./scripts_ota.sh HOST TOKEN
HOST=${1:-${PANEL_HOST:-192.168.1.159}}
TOK=${2:-${PANEL_TOKEN:-$(cat /tmp/sd_token 2>/dev/null)}}
cd "$(dirname "$0")/py"
tar cf /tmp/app.tar --exclude=__pycache__ --exclude=tests --exclude=deploy.sh board.py main.py boot.py core ui www
curl -s -m 300 -X POST -H "X-OTA-Token: $TOK" --data-binary @/tmp/app.tar "http://$HOST/api/ota/py"; echo
