#!/bin/bash
# Full-page redraw time per screen (ms, 3 runs each).   PANEL_HOST=... PANEL_TOKEN=... ./scripts/bench.sh
. "$(dirname "$0")/common.sh"
[ -n "${1:-}" ] && PANEL_HOST=$1
need_host; need_token
H=http://$PANEL_HOST
for i in 1 2 3 4 5 6; do curl -s -X POST "$H/api/swipe?dir=right" >/dev/null; done; sleep 2    # go to the first page
for i in 0 1 2 3 4 5; do
    curl -s -m 20 -X POST -H "X-OTA-Token: $PANEL_TOKEN" "$H/api/bench/render"; echo
    curl -s -X POST "$H/api/swipe?dir=left" >/dev/null; sleep 2.5
done
