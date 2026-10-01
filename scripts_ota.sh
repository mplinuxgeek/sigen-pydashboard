#!/bin/bash
# Push the Python app (py/) to the panel over the network (about 45 s, rolls back if the new code does not boot).
#   PANEL_HOST=192.168.1.50 PANEL_TOKEN=abcd ./scripts_ota.sh        or        ./scripts_ota.sh HOST TOKEN
. "$(dirname "$0")/scripts/common.sh"
[ -n "${1:-}" ] && PANEL_HOST=$1
[ -n "${2:-}" ] && PANEL_TOKEN=$2
need_host; need_token
cd "$(dirname "$0")/py"
TAR=$(mktemp)
trap 'rm -f "$TAR"' EXIT
tar cf "$TAR" --exclude=__pycache__ --exclude=tests --exclude=deploy.sh board.py main.py boot.py core ui www
curl -s -m 300 -X POST -H "X-OTA-Token: $PANEL_TOKEN" --data-binary @"$TAR" "http://$PANEL_HOST/api/ota/py"; echo
